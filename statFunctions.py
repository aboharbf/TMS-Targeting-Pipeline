import itertools

import pandas as pd
import ptitprince as pt # Only needed for raincloud plot
from scipy.stats import ttest_rel
from statsmodels.stats.anova import AnovaRM


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


def rm_test(data, var, groups):
    """
    One-way repeated measures test of mean_distance across levels of var (data has one row per subject x level).
    Paired t-test for 2 levels, RM-ANOVA + Bonferroni-corrected paired t-tests for more.
    Returns a dict in the same layout as main.ipynb's stat_results entries, plus the full 'pairwise' list.
    """
    data = data.sort_values('subject')
    group_data = [data[data[var] == val]['mean_distance'].values for val in groups]

    if len(groups) == 2:
        stat, p_val = ttest_rel(group_data[0], group_data[1])
        return {'test': 'ttest', 'stat': stat, 'p_val': p_val, 'stat_name': 't', 'groups': groups,
                'pairwise': [], 'comparisons': [{'group1': groups[0], 'group2': groups[1],
                                                 'pval': p_val, 'pos1': 0, 'pos2': 1}]}

    res = AnovaRM(data=data, depvar='mean_distance', subject='subject', within=[var]).fit()
    stat = res.anova_table['F Value'].values[0]
    p_val = res.anova_table['Pr > F'].values[0]

    n_comparisons = len(groups) * (len(groups) - 1) // 2
    pairwise_results = []
    for g1, g2 in itertools.combinations(range(len(groups)), 2):
        t_stat, t_pval = ttest_rel(group_data[g1], group_data[g2])
        corrected_pval = min(t_pval * n_comparisons, 1.0)
        pairwise_results.append({
            'group1': groups[g1], 'group2': groups[g2],
            'meandiff': group_data[g2].mean() - group_data[g1].mean(),
            't_stat': t_stat, 'p_raw': t_pval, 'p_corrected': corrected_pval,
            'reject': corrected_pval < 0.05,
            'pos1': g1, 'pos2': g2,
        })

    # Significant comparisons for plotting, shortest bracket first
    comparisons = [{'group1': r['group1'], 'group2': r['group2'], 'pval': r['p_corrected'],
                    'pos1': r['pos1'], 'pos2': r['pos2']} for r in pairwise_results if r['reject']]
    comparisons.sort(key=lambda x: abs(x['pos2'] - x['pos1']))

    return {'test': 'anova', 'stat': stat, 'p_val': p_val, 'stat_name': 'F', 'groups': groups,
            'pairwise': pairwise_results, 'comparisons': comparisons}


def format_pairwise(r):
    """One row of the post-hoc table, for printing and the stats file."""
    sig = '*' if r['reject'] else ''
    comparison = f"{r['group1']:g} vs {r['group2']:g}"
    return (f"{comparison:<16} {r['meandiff']:>10.3f} {r['t_stat']:>10.3f} "
            f"{r['p_raw']:>12.2e} {r['p_corrected']:>12.2e} {sig:>5}")


PAIRWISE_HEADER = f"{'Comparison':<16} {'mean_diff':>10} {'t':>10} {'p_raw':>12} {'p_corr':>12} {'sig':>5}"


def print_rm_test(result, label):
    if result['test'] == 'ttest':
        print(f"{label}: paired t-test, t={result['stat']:.3f}, p={result['p_val']:.2e}")
        return
    print(f"{label}: RM-ANOVA, F={result['stat']:.3f}, p={result['p_val']:.2e}")
    print(f"  Post-hoc paired t-tests (Bonferroni corrected, k={len(result['pairwise'])}):")
    print('    ' + PAIRWISE_HEADER)
    for r in result['pairwise']:
        print('    ' + format_pairwise(r))


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
