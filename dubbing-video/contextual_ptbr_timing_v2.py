"""One audited timing repair; parent recordings/receipts are never overwritten."""
import contextual_ptbr_candidate as pipeline

if __name__=='__main__':
    pipeline.configure_timing_revision()
    pipeline.main()
