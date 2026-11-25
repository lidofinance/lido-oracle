from fastapi import FastAPI
from prometheus_client import CollectorRegistry, GCCollector, PlatformCollector, ProcessCollector
from prometheus_fastapi_instrumentator import Instrumentator, metrics

from src import variables
from src.metrics.prometheus.basic import BUILD_INFO
from src.utils.build import get_build_info


# To avoid auto-scraping metrics from `src/metrics/prometheus` and any other possible places.
# TODO: once we achieve a proper metrics modules separation we can use the default registry.
CUSTOM_REGISTRY = CollectorRegistry()
CUSTOM_REGISTRY.register(BUILD_INFO)
# The default registry gets these collectors on import; a custom registry needs them added by hand.
ProcessCollector(registry=CUSTOM_REGISTRY)
PlatformCollector(registry=CUSTOM_REGISTRY)
GCCollector(registry=CUSTOM_REGISTRY)


def attach_metrics(app: FastAPI):
    build_info = get_build_info()
    BUILD_INFO.info(build_info)

    instrumentator = Instrumentator(
        excluded_handlers=["/health", "/metrics"],
        registry=CUSTOM_REGISTRY,
    )
    instrumentator.add(
        metrics.default(metric_namespace=variables.PERFORMANCE_WEB_SERVER_METRICS_PREFIX, registry=CUSTOM_REGISTRY)
    )
    instrumentator.instrument(app).expose(
        app,
        include_in_schema=True,
        should_gzip=True,
    )
