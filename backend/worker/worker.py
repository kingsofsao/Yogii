import time
import os
import logging
from backend.worker.tasks import process_batch_reconciliation, update_transaction_graph_cache

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [YOGII-WORKER]: %(message)s")
logger = logging.getLogger("yogii.worker")

def run_worker_loop():
    """Simple robust polling worker loop for background tasks."""
    logger.info("Yogii background worker process started. Monitoring task queue...")
    iteration = 0
    try:
        while True:
            time.sleep(10)
            iteration += 1
            if iteration % 6 == 0:  # Every 60 seconds
                update_transaction_graph_cache()
    except KeyboardInterrupt:
        logger.info("Yogii background worker stopped.")

if __name__ == "__main__":
    run_worker_loop()
