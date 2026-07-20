import sys
from app.snapshot.models import SnapshotProvider

def get_backend_provider() -> SnapshotProvider:
    """
    Factory function resolving platform-specific BackendSnapshotProvider.
    """
    from app.snapshot.providers.backend import MacOSBackendSnapshotProvider, LinuxBackendSnapshotProvider
    if sys.platform == "darwin":
        return MacOSBackendSnapshotProvider()
    return LinuxBackendSnapshotProvider()

def get_nginx_provider() -> SnapshotProvider:
    """
    Factory function resolving platform-specific NginxSnapshotProvider.
    """
    from app.snapshot.providers.nginx import MacOSNginxSnapshotProvider, LinuxNginxSnapshotProvider
    if sys.platform == "darwin":
        return MacOSNginxSnapshotProvider()
    return LinuxNginxSnapshotProvider()

def get_postgres_provider() -> SnapshotProvider:
    """
    Factory function resolving platform-specific PostgreSQLSnapshotProvider.
    """
    from app.snapshot.providers.postgres import MacOSPostgreSQLSnapshotProvider, LinuxPostgreSQLSnapshotProvider
    if sys.platform == "darwin":
        return MacOSPostgreSQLSnapshotProvider()
    return LinuxPostgreSQLSnapshotProvider()

def get_cloudflared_provider() -> SnapshotProvider:
    """
    Factory function resolving platform-specific CloudflaredSnapshotProvider.
    """
    from app.snapshot.providers.cloudflared import MacOSCloudflaredSnapshotProvider, LinuxCloudflaredSnapshotProvider
    if sys.platform == "darwin":
        return MacOSCloudflaredSnapshotProvider()
    return LinuxCloudflaredSnapshotProvider()

def get_redis_provider() -> SnapshotProvider:
    """
    Factory function resolving platform-specific RedisSnapshotProvider.
    """
    from app.snapshot.providers.redis import MacOSRedisSnapshotProvider, LinuxRedisSnapshotProvider
    if sys.platform == "darwin":
        return MacOSRedisSnapshotProvider()
    return LinuxRedisSnapshotProvider()

def get_system_provider() -> SnapshotProvider:
    """
    Factory function resolving platform-specific SystemSnapshotProvider.
    """
    from app.snapshot.providers.system import MacOSSystemSnapshotProvider, LinuxSystemSnapshotProvider
    if sys.platform == "darwin":
        return MacOSSystemSnapshotProvider()
    return LinuxSystemSnapshotProvider()
