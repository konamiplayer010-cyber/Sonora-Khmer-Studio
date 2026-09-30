This folder holds the Clean & Clear neural weights.

Both tools (Sonora Studio and the batch pipeline) share this one copy, so the
~420 MB download happens only ONCE:

    MossFormer2_SE_48K\last_best_checkpoint.pt        (~221 MB, denoise)
    MossFormer2_SR_48K\last_best_checkpoint_m.pt      (~218 MB, super-resolution)

Nothing to do by hand - "install Clean and Clear engine" (menu 4) or the
Sonora Studio "get engine" button fills this folder automatically.
If you move or copy this whole studio folder, copy this folder with it and
nothing needs re-downloading.
