from abc import ABC, abstractmethod
import time
from datetime import datetime
from app.evidence import CollectorResult, EvidencePackage

class BaseCollector(ABC):
    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def collect(self, config: dict) -> CollectorResult:
        """
        Runs collection logic and returns a CollectorResult.
        Must not write files, print directly, or terminate the process.
        """
        pass

class CollectorManager:
    _registry: dict[str, type[BaseCollector]] = {}

    @classmethod
    def register(cls, name: str, collector_cls: type[BaseCollector]):
        """
        Registers a collector class.
        """
        cls._registry[name] = collector_cls

    @classmethod
    def unregister(cls, name: str):
        """
        Unregisters a collector class.
        """
        if name in cls._registry:
            del cls._registry[name]

    @classmethod
    def run(cls, incident_id: str, target_name: str, config: dict) -> EvidencePackage:
        """
        Executes all registered and enabled collectors.
        Returns an EvidencePackage.
        """
        collectors_config = config.get("collectors", {})
        results = []
        
        start_package_time = time.perf_counter()
        collected_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        executed_count = 0
        success_count = 0
        failed_count = 0
        
        for name, collector_cls in cls._registry.items():
            collector_cfg = collectors_config.get(name, {})
            # Only execute if explicitly enabled in config
            if not isinstance(collector_cfg, dict) or not collector_cfg.get("enabled", False):
                continue
                
            executed_count += 1
            started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            start_time = time.perf_counter()
            
            try:
                collector_instance = collector_cls(name)
                res = collector_instance.collect(collector_cfg)
                
                # Verify that it returned a CollectorResult
                if not isinstance(res, CollectorResult):
                    raise TypeError("Collector did not return a CollectorResult object")
                
                results.append(res)
                if res.success:
                    success_count += 1
                else:
                    failed_count += 1
            except Exception as e:
                finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                failed_count += 1
                results.append(CollectorResult(
                    collector_name=name,
                    success=False,
                    started_at=started_at,
                    finished_at=finished_at,
                    duration_ms=round(duration_ms, 2),
                    data=None,
                    error=str(e)
                ))
                
        total_time_ms = (time.perf_counter() - start_package_time) * 1000.0
        
        print(
            f"Collectors Executed: {executed_count} | "
            f"Successful: {success_count} | "
            f"Failed: {failed_count} | "
            f"Total Collection Time: {round(total_time_ms, 2)} ms",
            flush=True
        )
        
        return EvidencePackage(
            incident_id=incident_id,
            target_name=target_name,
            collected_at=collected_at,
            collector_results=results
        )

# Register collectors
from app.collector.nginx import NginxCollector
from app.collector.cloudflared import CloudflaredCollector
from app.collector.uvicorn import UvicornCollector

CollectorManager.register("nginx", NginxCollector)
CollectorManager.register("cloudflared", CloudflaredCollector)
CollectorManager.register("uvicorn", UvicornCollector)
