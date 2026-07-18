import os
import time
import json
import logging
import concurrent.futures
from datetime import datetime, timezone
from typing import List, Dict, Any
from app.snapshot.models import SnapshotContext, SnapshotProvider, SnapshotResult, CapturedArtifact, ProviderCaptureResult

class SnapshotEngine:
    _providers: List[SnapshotProvider] = []
    _logger = logging.getLogger("SnapshotEngine")

    @classmethod
    def register_provider(cls, provider: SnapshotProvider) -> None:
        """
        Registers a snapshot provider.
        """
        if provider not in cls._providers:
            cls._providers.append(provider)

    @classmethod
    def _validate_name(cls, name: str) -> bool:
        """
        Ensures a name contains no absolute paths or path traversal escape sequences.
        """
        if not name:
            return False
        # Reject absolute paths or parent directory traversal sequences
        if ".." in name or "/" in name or "\\" in name or os.path.isabs(name):
            return False
        return True

    @classmethod
    def run(cls, incident_id: str, target_name: str, config: dict) -> Dict:
        """
        Executes all registered snapshot providers and writes the manifest.json file.
        """
        start_time = time.perf_counter()
        
        # Resolve target directory: incidents/INC-XXXX/evidence
        base_dir = os.path.join("incidents", incident_id)
        evidence_dir = os.path.join(base_dir, "evidence")
        os.makedirs(evidence_dir, exist_ok=True)
        
        results: List[SnapshotResult] = []
        successful_count = 0
        failed_count = 0
        
        # Read snapshot configs
        snapshot_config = config.get("snapshot", {})
        
        for provider in cls._providers:
            # Strictly validate provider name to prevent directory traversal
            if not cls._validate_name(provider.name):
                cls._logger.error(f"Security Warning: Rejected invalid provider name: {provider.name}")
                failed_count += 1
                results.append(SnapshotResult(
                    provider_name=provider.name,
                    status="FAILED",
                    execution_time_ms=0.0,
                    error_message="Invalid/unsafe provider name blocked"
                ))
                continue

            provider_config = snapshot_config.get(provider.name, {})
            # By default, providers are enabled unless explicitly set to false
            enabled = provider_config.get("enabled", True)
            if not enabled:
                continue
                
            timeout = provider_config.get("timeout_seconds", provider.timeout_seconds)
            
            # Create a dedicated directory for the provider
            provider_dir = os.path.join(evidence_dir, provider.name)
            os.makedirs(provider_dir, exist_ok=True)
            
            context = SnapshotContext(
                incident_id=incident_id,
                target_name=target_name,
                config=config,
                evidence_dir=provider_dir,
                timestamp=datetime.now(timezone.utc),
                logger=cls._logger
            )
            
            provider_start = time.perf_counter()
            status = "SUCCESS"
            error_msg = ""
            output_file = ""
            
            try:
                # Enforce timeout using a ThreadPoolExecutor
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(provider.capture, context)
                    # Block until done or timeout reached
                    captured_data = future.result(timeout=timeout)
                
                # Check for new structured ProviderCaptureResult object
                if isinstance(captured_data, ProviderCaptureResult):
                    total_bytes = 0
                    artifact_details = []
                    
                    for artifact in captured_data.artifacts:
                        # Strictly validate artifact name to prevent directory traversal
                        if not cls._validate_name(artifact.name):
                            cls._logger.error(f"Security Warning: Blocked unsafe artifact name: {artifact.name}")
                            continue
                            
                        # Write artifact file if status is SUCCESS and content is present
                        if artifact.status == "SUCCESS" and artifact.content:
                            artifact_path = os.path.join(provider_dir, artifact.name)
                            with open(artifact_path, "w", encoding="utf-8") as f:
                                f.write(artifact.content)
                            total_bytes += len(artifact.content.encode("utf-8"))
                            
                        # Build metadata properties for this artifact
                        detail = {
                            "name": artifact.name,
                            "status": artifact.status,
                            "captured_at": artifact.captured_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "duration_ms": artifact.duration_ms,
                            "bytes_captured": artifact.bytes_captured,
                            "lines_captured": artifact.lines_captured,
                            "truncated": artifact.truncated,
                            "redaction_applied": artifact.redaction_applied
                        }
                        if artifact.exit_code is not None:
                            detail["exit_code"] = artifact.exit_code
                        if artifact.error_message:
                            detail["error_message"] = artifact.error_message
                        if artifact.capture_method:
                            detail["capture_method"] = artifact.capture_method
                            
                        artifact_details.append(detail)
                    
                    # Localized metadata sidecar file
                    metadata = {
                        "captured_at": context.timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "provider": provider.name,
                        "status": captured_data.status,
                        "duration_ms": round((time.perf_counter() - provider_start) * 1000, 2),
                        "artifacts": artifact_details,
                        "bytes_written": total_bytes
                    }
                    metadata_path = os.path.join(provider_dir, "metadata.json")
                    with open(metadata_path, "w", encoding="utf-8") as f:
                        json.dump(metadata, f, indent=2)
                    
                    status = captured_data.status
                    successful_count += 1
                    
                # Backward Compatibility: Handle raw string returns (Batch 1 behavior)
                elif isinstance(captured_data, str) and captured_data:
                    output_file_name = "capture.log"
                    output_path = os.path.join(provider_dir, output_file_name)
                    with open(output_path, "w", encoding="utf-8") as f:
                        f.write(captured_data)
                    output_file = f"evidence/{provider.name}/{output_file_name}"
                    
                    # Localized metadata sidecar file
                    metadata = {
                        "captured_at": context.timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "provider": provider.name,
                        "status": "SUCCESS",
                        "duration_ms": round((time.perf_counter() - provider_start) * 1000, 2),
                        "bytes_written": len(captured_data.encode("utf-8"))
                    }
                    metadata_path = os.path.join(provider_dir, "metadata.json")
                    with open(metadata_path, "w", encoding="utf-8") as f:
                        json.dump(metadata, f, indent=2)
                        
                    successful_count += 1
                else:
                    status = "FAILED"
                    error_msg = "Provider returned empty or invalid payload structure"
                    failed_count += 1
                
            except concurrent.futures.TimeoutError:
                status = "TIMEOUT"
                error_msg = "Provider capture execution exceeded timeout"
                failed_count += 1
                cls._logger.warning(f"Provider {provider.name} timed out.")
            except Exception as e:
                status = "FAILED"
                error_msg = str(e)
                failed_count += 1
                cls._logger.exception(f"Provider {provider.name} failed during execution.")
            
            duration_ms = round((time.perf_counter() - provider_start) * 1000, 2)
            results.append(SnapshotResult(
                provider_name=provider.name,
                status=status,
                execution_time_ms=duration_ms,
                output_file=output_file,
                error_message=error_msg
            ))
            
        total_duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        
        # Build manifest payload
        manifest = {
            "snapshot_schema_version": 1,
            "incident_id": incident_id,
            "execution_summary": {
                "total_providers": len(cls._providers),
                "successful": successful_count,
                "failed": failed_count,
                "total_duration_ms": total_duration_ms
            },
            "results": [
                {
                    "provider_name": r.provider_name,
                    "status": r.status,
                    "execution_time_ms": r.execution_time_ms,
                    "output_file": r.output_file,
                    "error_message": r.error_message
                }
                for r in results
            ]
        }
        
        # Save manifest.json under evidence/
        manifest_path = os.path.join(evidence_dir, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
            
        return manifest
