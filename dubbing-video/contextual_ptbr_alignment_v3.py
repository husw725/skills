"""One speed calibration and reuse of a previously approved production onset."""
import contextual_ptbr_candidate as pipeline

if __name__=='__main__':
    pipeline.configure_alignment_revision()
    pipeline.main()
