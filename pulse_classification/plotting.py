"""Port of ``make_plot.m`` -- 3-panel figure (oriented motion / extracted pulse /
residual)."""

from __future__ import annotations

from pathlib import Path

import numpy as np


def make_plot(j, signal, pulse_th, resid_th, dt, sta, out_dir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    signal = np.asarray(signal)
    n = signal.size
    time = np.arange(1, n + 1) * dt
    ylim = np.max(np.abs(signal)) * 1.05

    fig, axes = plt.subplots(3, 1, figsize=(8, 6), sharex=True)
    axes[0].plot(time, signal, "-k", lw=1.2, label="Oriented ground motion")
    axes[1].plot(time, pulse_th, "-r", lw=1.2, label="Extracted pulse")
    axes[2].plot(time, resid_th, "-k", lw=1.2, label="Residual ground motion")
    for ax in axes:
        ax.set_ylim(-ylim, ylim)
        ax.legend(loc="upper right", fontsize=9)
    axes[0].set_title(f"{sta}-{j}", fontsize=13)
    axes[1].set_ylabel("Velocity [cm/s]")
    axes[2].set_xlabel("Time [s]")
    fig.tight_layout()

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_dir / f"{sta}_{j}_pulse.png", dpi=120)
    plt.close(fig)
