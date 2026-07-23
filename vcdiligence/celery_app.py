import os
from celery import Celery

REDIS_URL = os.getenv("REDIS_URL")

# If REDIS_URL is not set, we default to eager mode (synchronous local execution)
# so the system is fully functional without a Redis instance.
if REDIS_URL:
    broker_url = REDIS_URL
    result_backend = REDIS_URL
    always_eager = False
else:
    broker_url = "redis://localhost:6379/0"
    result_backend = "redis://localhost:6379/0"
    always_eager = True

celery_app = Celery(
    "vcdiligence",
    broker=broker_url,
    backend=result_backend,
    include=["vcdiligence.tasks"]
)

celery_app.conf.update(
    task_always_eager=always_eager,
    timezone="UTC",
    broker_connection_retry_on_startup=True,
)
