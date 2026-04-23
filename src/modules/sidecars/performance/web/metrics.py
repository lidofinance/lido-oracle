from fastapi import FastAPI
from prometheus_client import CollectorRegistry
from prometheus_fastapi_instrumentator import Instrumentator, metrics

import variables
from metrics.prometheus.basic import BUILD_INFO
from utils.build import get_build_info


# To avoid auto-scraping metrics from `src/metrics/prometheus` and any other possible places.
# TODO: once we achieve a proper metrics modules separation we can use the default registry.
CUSTOM_REGISTRY = CollectorRegistry()
CUSTOM_REGISTRY.register(BUILD_INFO)


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
