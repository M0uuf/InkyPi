import logging

logger = logging.getLogger(__name__)


def shutdown_display_stack(refresh_task, display_manager):
    """Stop background refresh work, then release display resources best-effort."""
    try:
        refresh_task.stop()
    except Exception:
        logger.exception("Exception while stopping refresh task during shutdown")

    try:
        display_manager.close()
    except Exception:
        logger.exception("Exception while closing display manager during shutdown")
