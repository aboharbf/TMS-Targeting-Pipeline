import matplotlib as mpl
import matplotlib.pyplot as plt

def svg_editing():
    """Configure matplotlib for SVG output optimized for editing."""
    config = {
        # SVG-specific
        'svg.fonttype': 'none',
        'svg.hashsalt': None,
        
        # Figure settings
        'figure.figsize': (8, 6),
        'figure.dpi': 300,
        'figure.autolayout': False,
        'figure.constrained_layout.use': True,
        
        # Save settings
        'savefig.dpi': 300,
        'savefig.bbox': 'tight',
        'savefig.transparent': False,
        'savefig.format': 'svg',
        
        # Font settings
        'font.size': 12,
        'font.family': 'sans-serif',
        'axes.labelsize': 14,
        'axes.titlesize': 16,
        'xtick.labelsize': 12,
        'ytick.labelsize': 12,
        'legend.fontsize': 12,
        
        # Style settings
        'lines.linewidth': 2,
        'axes.grid': True,
        'grid.alpha': 0.3,
        'axes.axisbelow': True,
    }
    mpl.rcParams.update(config)