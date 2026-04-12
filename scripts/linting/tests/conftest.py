"""Pytest fixtures for Traefik Swarm linter tests.

Fixtures are defined here (not in test files) to avoid W0621
"Redefining name from outer scope" warnings. This is the
pytest-recommended pattern for fixture organization.
"""

import pytest

TRAEFIK_IMAGE = "traefik:v3.6"
TRAEFIK_ENABLE_LABEL = "traefik.enable=true"
NGINX_IMAGE = "nginx:1.27"


@pytest.fixture
def valid_traefik_compose() -> dict:
    """Valid Traefik compose for Swarm with all correct settings."""
    return {
        "services": {
            "traefik": {
                "image": TRAEFIK_IMAGE,
                "command": [
                    "--providers.swarm=true",
                    "--providers.swarm.endpoint=unix:///var/run/docker.sock",
                ],
                "environment": {
                    "CF_DNS_API_TOKEN_FILE": "/run/secrets/cf_token",
                    "DOMAIN_NAME": "${DOMAIN_NAME?DOMAIN_NAME is required}",
                },
                "secrets": ["cf_token"],
                "deploy": {
                    "mode": "replicated",
                    "replicas": 1,
                    "labels": [
                        TRAEFIK_ENABLE_LABEL,
                        "traefik.http.routers.traefik-rtr.rule=Host(`traefik.${DOMAIN_NAME?DOMAIN_NAME is required}`)",
                        "traefik.http.routers.traefik-rtr.service=api@internal",
                        "traefik.http.services.traefik-svc.loadbalancer.server.port=8080",
                    ],
                },
            }
        }
    }


@pytest.fixture
def compose_labels_at_service_level() -> dict:
    """Labels at service level instead of deploy.labels - ERROR for Swarm."""
    return {
        "services": {
            "traefik": {
                "image": TRAEFIK_IMAGE,
                "labels": [
                    TRAEFIK_ENABLE_LABEL,
                    "traefik.http.routers.traefik-rtr.rule=Host(`traefik.example.com`)",
                ],
            }
        }
    }


@pytest.fixture
def missing_loadbalancer_port() -> dict:
    """Missing loadbalancer.server.port label - ERROR for Swarm."""
    return {
        "services": {
            "traefik": {
                "image": TRAEFIK_IMAGE,
                "deploy": {
                    "labels": [
                        TRAEFIK_ENABLE_LABEL,
                        "traefik.http.routers.traefik-rtr.rule=Host(`traefik.example.com`)",
                        "traefik.http.routers.traefik-rtr.service=api@internal",
                    ],
                },
            }
        }
    }


@pytest.fixture
def docker_provider_instead_of_swarm() -> dict:
    """Uses --providers.docker instead of --providers.swarm - ERROR."""
    return {
        "services": {
            "traefik": {
                "image": TRAEFIK_IMAGE,
                "command": [
                    "--providers.docker=true",
                    "--providers.docker.endpoint=unix:///var/run/docker.sock",
                ],
            }
        }
    }


@pytest.fixture
def network_mode_host_service() -> dict:
    """Uses network_mode: host - ERROR for Swarm."""
    return {
        "services": {
            "fail2ban": {
                "image": "crazymax/fail2ban:1.0.0",
                "network_mode": "host",
            }
        }
    }


@pytest.fixture
def restart_instead_of_deploy_restart() -> dict:
    """Uses restart: instead of deploy.restart_policy - ERROR."""
    return {
        "services": {
            "traefik": {
                "image": TRAEFIK_IMAGE,
                "restart": "unless-stopped",
            }
        }
    }


@pytest.fixture
def env_var_without_file_suffix() -> dict:
    """Uses API_TOKEN instead of API_TOKEN_FILE for secrets - WARN."""
    return {
        "services": {
            "traefik": {
                "image": TRAEFIK_IMAGE,
                "environment": {
                    "CF_DNS_API_TOKEN": "secret-value",
                },
                "secrets": ["cf_token"],
            }
        }
    }


@pytest.fixture
def multi_network_traefik_enabled_service_missing_docker_network() -> dict:
    """Service joins multiple networks and is traefik-enabled, but lacks traefik.docker.network."""
    return {
        "services": {
            "app": {
                "image": NGINX_IMAGE,
                "networks": ["traefik_public", "socket_proxy_network"],
                "deploy": {"labels": [TRAEFIK_ENABLE_LABEL]},
            }
        }
    }


@pytest.fixture
def multi_network_traefik_enabled_service_with_docker_network() -> dict:
    """Service joins multiple networks and is traefik-enabled, with traefik.docker.network set."""
    return {
        "services": {
            "app": {
                "image": NGINX_IMAGE,
                "networks": ["traefik_public", "socket_proxy_network"],
                "deploy": {
                    "labels": [
                        TRAEFIK_ENABLE_LABEL,
                        "traefik.docker.network=traefik_public",
                    ]
                },
            }
        }
    }


@pytest.fixture
def multi_network_traefik_enabled_service_with_wrong_docker_network() -> dict:
    """Service joins multiple networks but traefik.docker.network points to a network it is not on."""
    return {
        "services": {
            "app": {
                "image": NGINX_IMAGE,
                "networks": ["traefik_public", "socket_proxy_network"],
                "deploy": {
                    "labels": [
                        TRAEFIK_ENABLE_LABEL,
                        "traefik.docker.network=other_network",
                    ]
                },
            }
        }
    }
