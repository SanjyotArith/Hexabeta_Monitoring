import os

def _tail_file(path: str, max_lines: int, max_bytes: int) -> tuple[str, bool, int, int]:
    """
    Forensically tails a log file, seeking backwards from the end to limit memory consumption.
    Returns (content, truncated, lines_read, bytes_read).
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")
    if not os.access(path, os.R_OK):
        raise PermissionError(f"File not readable: {path}")
        
    file_size = os.path.getsize(path)
    if file_size == 0:
        return "", False, 0, 0
        
    read_size = min(max_bytes, file_size)
    
    with open(path, "rb") as f:
        f.seek(-read_size, os.SEEK_END)
        raw_data = f.read(read_size)
        
    decoded = raw_data.decode("utf-8", errors="ignore")
    lines = decoded.splitlines()
    
    truncated = (file_size > max_bytes)
    
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
        truncated = True
        
    content = "\n".join(lines)
    bytes_captured = len(content.encode("utf-8"))
    return content, truncated, len(lines), bytes_captured
