import itertools

import numpy as np
import pandas as pd
import ptitprince as pt # Only needed for raincloud plot
from scipy.spatial.distance import pdist
from scipy.stats import ttest_rel
from statsmodels.stats.anova import AnovaRM


SECTION = '=' * 90

PAIRWISE_HEADER = (f"{'Comparison':<22} {'mean_diff':>10} {'SD_diff':>10} {'t':>10} "
                   f"{'p_raw':>12} {'p_corr':>12} {'sig':>5}")


def fmt_level(g):
    """Level label for tables: strings as-is, numbers compactly (0.3, 4)."""
    return g if isinstance(g, str) else f'{g:g}'


# --- Distances ---

def session_distance(g):
    """Number of sessions and mean pairwise Euclidean distance between their X/Y/Z peaks."""
    dists = pdist(g[['X', 'Y', 'Z']].values, metric='euclidean')
    return pd.Series({'n_sessions': len(g),
                      'mean_distance': round(dists.mean(), 2) if len(dists) else np.nan})


def session_distances(df, grouping_vars):
    """One row per grouping_vars cell with n_sessions and mean_distance."""
    combodf = df.groupby(grouping_vars).apply(session_distance, include_groups=False).reset_index()
    combodf['n_sessions'] = combodf['n_sessions'].astype(int)
    return combodf


def pairwise_distances(df, grouping_vars):
    """Every session pair's Euclidean distance within each grouping_vars cell (long format)."""
    rows = []
    for keys, g in df.groupby(grouping_vars):
        dists = pdist(g[['X', 'Y', 'Z']].values, metric='euclidean')
        # pdist's condensed order matches itertools.combinations over the rows
        for (i, j), d in zip(itertools.combinations(range(len(g)), 2), dists):
            rows.append({**dict(zip(grouping_vars, keys)), 'session_i': i, 'session_j': j,
                         'euclidean_distance': round(d, 2)})
    return pd.DataFrame(rows)


def complete_design(combodf, cell_vars):
    """
    Drop subjects AnovaRM can't use: fewer than 2 sessions in some cell (no distance to compute),
    or missing cells (AnovaRM needs a full design).
    """
    singleSes = combodf.loc[combodf['n_sessions'] < 2, 'subject'].unique().tolist()
    if singleSes:
        print(f'Dropping {len(singleSes)} subjects with < 2 sessions in some cell: {singleSes}')
        combodf = combodf[~combodf['subject'].isin(singleSes)]

    nCells = combodf[cell_vars].drop_duplicates().shape[0]
    cellsPerSubj = combodf.groupby('subject').size()
    incomplete = cellsPerSubj[cellsPerSubj < nCells].index.tolist()
    if incomplete:
        print(f'Dropping {len(incomplete)} subjects with incomplete cells: {incomplete}')
        combodf = combodf[~combodf['subject'].isin(incomplete)]

    print(f"{combodf['subject'].nunique()} subjects x {nCells} cells")
    return combodf.reset_index(drop=True)


def subject_means(combodf, *vars):
    """Average mean_distance over all other factors: one row per subject x level(s) of vars."""
    return combodf.groupby(['subject', *vars], observed=True)['mean_distance'].mean().reset_index()


# --- Subject selection ---

# Factors that define a cell in each dataset. Every included subject needs >= 2 sessions in every cell.
BASE_CELL_VARS = ['target', 'clustMask', 'sequence_type']    # coordinatesAll_original.csv (main.ipynb)
PARAM_CELL_VARS = ['fwhm', 'motion', 'target', 'clustMask']  # coordinatesAll_param.csv (main_paramGrid.ipynb)

# Levels expected from x07.blur_censor_param.csh; checked against the param data after decoding.
PARAM_GRID = {'fwhm': [0, 2, 4, 6], 'motion': [0.15, 0.3, 0.45]}

SUBJECT_MODES = ('base_only', 'param_only', 'both')


def prep_param(df, peak_sign='abs'):
    """
    Keep one peak sign and only the grid variants, decoding fwhm and motion from runTag
    ('param-b4m0p3' -> fwhm 4, motion 0.3). The base 'param' run and untagged rows are dropped:
    'param-b4m0p3' repeats the base run's settings, so keeping both would double that grid point.
    """
    df = df[df['sign'] == peak_sign].copy()
    parsed = df['runTag'].str.extract(r'-b(?P<fwhm>\d+)m(?P<motion>\d+p\d+)$')
    df['fwhm'] = parsed['fwhm'].astype(float)
    df['motion'] = parsed['motion'].str.replace('p', '.').astype(float)

    print('Rows dropped (not a grid variant):')
    print(df.loc[df['fwhm'].isna(), 'runTag'].fillna('<untagged>').value_counts().to_string())
    df = df[df['fwhm'].notna()].copy()

    for var, expected in PARAM_GRID.items():
        found = sorted(df[var].unique())
        assert found == expected, f'{var} levels {found} do not match PARAM_GRID {expected}'
    return df


def drop_nan_subjects(df):
    """Drop every subject with a missing X/Y/Z peak anywhere (peakZ is ignored: missing peaks also lack X/Y/Z)."""
    nanSubj = sorted(df.loc[df[['X', 'Y', 'Z']].isna().any(axis=1), 'subject'].unique())
    print(f'Subjects with NaNs - {len(nanSubj)}: {nanSubj}')
    return df[~df['subject'].isin(nanSubj)]


def drop_partial_sessions(df, cell_vars):
    """
    Drop sessions missing from some cell (e.g. a motion limit skipped for too few TRs),
    so each of a subject's mean distances is built from the same sessions.
    """
    nCells = df[cell_vars].drop_duplicates().shape[0]
    sesCells = df.drop_duplicates(['subject', 'session', *cell_vars]).groupby(['subject', 'session']).size()
    partialSes = sesCells[sesCells < nCells]
    print(f'Sessions missing cells ({nCells} expected): {"none" if partialSes.empty else ""}')
    if len(partialSes):
        print(partialSes.to_string())

    dropIdx = pd.MultiIndex.from_frame(df[['subject', 'session']]).isin(partialSes.index)
    if dropIdx.any():
        print(f'Dropped {dropIdx.sum()} rows from those sessions')
    return df[~dropIdx]


def design_subjects(df, cell_vars):
    """Subjects that pass complete_design, found from session counts so no distances are computed."""
    counts = df.groupby(['subject', *cell_vars]).size().rename('n_sessions').reset_index()
    return set(complete_design(counts, cell_vars)['subject'])


def select_subjects(base_df, param_df, mode='both', peak_sign='abs', match_sessions=True):
    """
    Clean both coordinate datasets and keep the subjects that mode selects, so every analysis
    in the paper can use the same subjects.

    base_df:  coordinatesAll_original.csv (main.ipynb)
    param_df: coordinatesAll_param.csv (main_paramGrid.ipynb)
    Read both with dtype={'subject': str, 'session': str} so subject IDs match between the files.

    Inclusion criteria, applied to each dataset separately:
      base:  no NaN coordinates in any sequence; >= 2 sessions in every BASE_CELL_VARS cell.
      param: peak_sign rows from the grid variants only (prep_param); no NaN coordinates; sessions
             missing some grid cell are dropped (if match_sessions); >= 2 sessions in every PARAM_CELL_VARS cell.

    mode chooses whose criteria define the subject list:
      'base_only'  - pass the base criteria (main.ipynb's original filtering)
      'param_only' - pass the param criteria (main_paramGrid.ipynb's original filtering)
      'both'       - pass both, so main.ipynb and main_paramGrid.ipynb analyze the same subjects

    Returns (base_df, param_df), each cleaned and limited to the kept subjects. A dataset is always
    cleaned by its own criteria (its analysis needs a full design), so the other dataset's mode
    has the same effect as 'both' (e.g. 'param_only' in main.ipynb).
    """
    if mode not in SUBJECT_MODES:
        raise ValueError(f"mode must be one of {SUBJECT_MODES}, got '{mode}'")
    for name, d in [('base_df', base_df), ('param_df', param_df)]:
        if not pd.api.types.is_string_dtype(d['subject']):
            raise TypeError(f"{name}['subject'] is not a string column: read the CSV with "
                            f"dtype={{'subject': str, 'session': str}} so subject IDs match between files")

    print('--- Base criteria (main.ipynb) ---')
    base = drop_nan_subjects(base_df)
    base = base[base['subject'].isin(design_subjects(base, BASE_CELL_VARS))]

    print('\n--- Param criteria (main_paramGrid.ipynb) ---')
    param = prep_param(param_df, peak_sign)
    param = drop_nan_subjects(param)
    if match_sessions:
        param = drop_partial_sessions(param, PARAM_CELL_VARS)
    param = param[param['subject'].isin(design_subjects(param, PARAM_CELL_VARS))]

    baseSubj, paramSubj = set(base['subject']), set(param['subject'])
    keep = {'base_only': baseSubj, 'param_only': paramSubj, 'both': baseSubj & paramSubj}[mode]

    print('\n--- Subject selection ---')
    print(f'Pass base criteria: {len(baseSubj)}, pass param criteria: {len(paramSubj)}, '
          f'pass both: {len(baseSubj & paramSubj)}')
    print(f'Pass base criteria only: {sorted(baseSubj - paramSubj)}')
    print(f'Pass param criteria only: {sorted(paramSubj - baseSubj)}')
    print(f"mode = '{mode}': {len(keep)} subjects kept")

    return (base[base['subject'].isin(keep)].reset_index(drop=True),
            param[param['subject'].isin(keep)].reset_index(drop=True))


# --- Tests ---

def rm_test(data, var, groups):
    """
    One-way repeated measures test of mean_distance across levels of var (data has one row per subject x level).
    Paired t-test for 2 levels, RM-ANOVA + Bonferroni-corrected paired t-tests for more.
    'pairwise' holds every paired comparison (the t-test itself when there are 2 levels, k=1);
    'comparisons' holds the brackets to plot.
    """
    data = data.sort_values('subject')
    group_data = [data[data[var] == val]['mean_distance'].values for val in groups]
    descriptives = [{'group': g, 'mean': v.mean(), 'sd': v.std(ddof=1), 'n': len(v)}
                    for g, v in zip(groups, group_data)]

    if len(groups) == 2:
        test, stat_name = 'ttest', 't'
        stat, p_val = ttest_rel(group_data[0], group_data[1])
    else:
        test, stat_name = 'anova', 'F'
        res = AnovaRM(data=data, depvar='mean_distance', subject='subject', within=[var]).fit()
        stat = res.anova_table['F Value'].values[0]
        p_val = res.anova_table['Pr > F'].values[0]

    # The paired t-statistic is mean_diff / (SD_diff / sqrt(n)), so a larger mean difference can still
    # give a higher p-value when the difference varies more between subjects (larger SD_diff).
    k = len(groups) * (len(groups) - 1) // 2
    pairwise = []
    for g1, g2 in itertools.combinations(range(len(groups)), 2):
        diff = group_data[g1] - group_data[g2]
        t_stat, p_raw = ttest_rel(group_data[g1], group_data[g2])
        p_corr = min(p_raw * k, 1.0)
        pairwise.append({
            'group1': groups[g1], 'group2': groups[g2],
            'meandiff': diff.mean(), 'sd_diff': diff.std(ddof=1), 'n': len(diff),
            't_stat': t_stat, 'p_raw': p_raw, 'p_corrected': p_corr,
            'reject': p_corr < 0.05,
            'pos1': g1, 'pos2': g2,
        })

    # Brackets: a 2-level test is always shown (ns included); post-hocs only when significant, shortest first
    shown = pairwise if test == 'ttest' else [r for r in pairwise if r['reject']]
    comparisons = [{'group1': r['group1'], 'group2': r['group2'], 'pval': r['p_corrected'],
                    'pos1': r['pos1'], 'pos2': r['pos2']} for r in shown]
    comparisons.sort(key=lambda x: abs(x['pos2'] - x['pos1']))

    return {'test': test, 'stat': stat, 'p_val': p_val, 'stat_name': stat_name, 'groups': groups,
            'k': k, 'descriptives': descriptives, 'pairwise': pairwise, 'comparisons': comparisons}


def rm_anova(data, within, label=None):
    """Factorial RM-ANOVA of mean_distance; prints the table under label (if given) and returns anova_table."""
    res = AnovaRM(data=data, depvar='mean_distance', subject='subject', within=within).fit()
    if label:
        print(label)
        print('=' * 60)
        print(res)
    return res.anova_table


# --- Reporting ---

def format_pairwise(r):
    """One row of the pairwise table, for printing and the stats file."""
    sig = '*' if r['reject'] else ''
    comparison = f"{fmt_level(r['group1'])} vs {fmt_level(r['group2'])}"
    return (f"{comparison:<22} {r['meandiff']:>10.3f} {r['sd_diff']:>10.3f} {r['t_stat']:>10.3f} "
            f"{r['p_raw']:>12.2e} {r['p_corrected']:>12.2e} {sig:>5}")


def format_rm_test(result, label, descriptives=False):
    """rm_test result as text: test statistic, optional group descriptives, pairwise table."""
    testName = 'paired t-test' if result['test'] == 'ttest' else 'RM-ANOVA'
    lines = [f"{label}: {testName}, {result['stat_name']}={result['stat']:.4f}, p={result['p_val']:.2e}"]

    if descriptives:
        lines.append('  Group descriptives:')
        for d in result['descriptives']:
            lines.append(f"    {fmt_level(d['group']):<12}: mean={d['mean']:.3f}, SD={d['sd']:.3f}, n={d['n']}")

    if result['test'] == 'anova':
        lines.append(f"  Post-hoc paired t-tests (Bonferroni corrected, k={result['k']}):")
    else:
        lines.append('  Paired comparison:')
    lines.append('    ' + PAIRWISE_HEADER)
    lines.append('    ' + '-' * len(PAIRWISE_HEADER))
    lines += ['    ' + format_pairwise(r) for r in result['pairwise']]
    return '\n'.join(lines)


def print_rm_test(result, label, descriptives=False):
    print(format_rm_test(result, label, descriptives))


def write_rm_test(f, result, label):
    f.write(format_rm_test(result, label, descriptives=True) + '\n\n')


def write_anova_table(f, table, label):
    """Full RM-ANOVA table plus a list of the significant effects."""
    f.write(label + '\n')
    f.write(SECTION + '\n\n')
    f.write(table.to_string())
    f.write('\n\n')
    sig_effects = table[table['Pr > F'] < 0.05]
    if len(sig_effects) > 0:
        f.write('Significant effects (p < 0.05):\n')
        for effect_name, row in sig_effects.iterrows():
            f.write(f"  {effect_name}: F={row['F Value']:.4f}, p={row['Pr > F']:.2e}\n")
    else:
        f.write('No significant effects at p < 0.05.\n')
    f.write('\n' + SECTION + '\n\n')


# --- Plotting ---

def plot_significance_brackets(ax, comparisons, y_min, y_max):
    """
    Plot significance brackets and stars on an axis.

    Parameters:
    -----------
    ax : matplotlib axis
        The axis to plot on
    comparisons : list of dict
        List of comparisons, each containing 'pos1', 'pos2', and 'pval'
    y_min : float
        Minimum y-value in the data
    y_max : float
        Maximum y-value in the data

    Returns:
    --------
    tuple : (new_y_min, new_y_max) adjusted limits to accommodate brackets
    """
    y_range = y_max - y_min

    if not comparisons:
        return (y_min - 0.05 * y_range, y_max + 0.05 * y_range)

    bracket_height_start = y_max + 0.02 * y_range
    bracket_spacing = 0.08 * y_range

    for comp_idx, comp in enumerate(comparisons):
        x1 = comp['pos1']
        x2 = comp['pos2']
        pval = comp['pval']

        # Determine star based on p-value
        if pval < 0.001:
            star = '***'
        elif pval < 0.01:
            star = '**'
        elif pval < 0.05:
            star = '*'
        else:
            star = 'ns'

        # Calculate bracket height (stack them)
        bracket_y = bracket_height_start + (comp_idx * bracket_spacing)
        star_y = bracket_y + 0.002 * y_range

        # Draw horizontal line
        ax.plot([x1, x2], [bracket_y, bracket_y], 'k-', linewidth=1.5)

        # Draw vertical ticks on both ends
        tick_height = 0.015 * y_range
        ax.plot([x1, x1], [bracket_y - tick_height, bracket_y], 'k-', linewidth=1.5)
        ax.plot([x2, x2], [bracket_y - tick_height, bracket_y], 'k-', linewidth=1.5)

        # Add star
        ax.text((x1 + x2) / 2, star_y, star, ha='center', va='bottom',
                fontsize=14, fontweight='bold')

    # Return adjusted y-limits to accommodate all brackets
    max_bracket_y = bracket_height_start + (len(comparisons) - 1) * bracket_spacing
    return (y_min - 0.05 * y_range, max_bracket_y + 0.10 * y_range)


def raincloud(ax, data, var, order, names, result, title, ylabel='Mean Pairwise Distance (mm)'):
    """Raincloud of mean_distance by var, with the test result under the title and significance brackets."""
    data = data.copy()
    data[var] = pd.Categorical(data[var], categories=order, ordered=True)

    pt.RainCloud(data=data, x=var, y='mean_distance', ax=ax,
        palette='Set2', hue=var, bw=0.3, width_viol=0.7, width_box=0.3,
        orient='v', alpha=0.6, dodge=False, pointplot=False, point_size=3,
        linewidth=2, jitter=0.15, box_showfliers=False, box_linewidth=2)

    ax.set_xticks(range(len(names)))
    ax.set_xticklabels(names)
    if ax.get_legend():
        ax.get_legend().remove()

    # Open up the plot to ensure the peaks for each distribution are visible.
    percSpread = 0.4
    xmin, xmax = ax.get_xlim()
    ax.set_xlim((xmin - percSpread, xmax + percSpread))

    new_y_min, new_y_max = plot_significance_brackets(
        ax=ax, comparisons=result['comparisons'],
        y_min=data['mean_distance'].min(), y_max=data['mean_distance'].max())
    ax.set_ylim(new_y_min, new_y_max)

    ax.set_title(title, fontsize=14, fontweight='bold', pad=22)
    ax.text(0.5, 1.01, f"{result['stat_name']}={result['stat']:.2f}, p={result['p_val']:.2e}",
            transform=ax.transAxes, ha='center', va='bottom', fontsize=12)
    ax.set_xlabel('', fontsize=11)
    ax.set_ylabel(ylabel, fontsize=11)
