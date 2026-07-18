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
