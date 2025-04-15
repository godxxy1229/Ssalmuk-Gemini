import socket

def find_available_port(start_port=8000, max_port=9000):
    """Find an available port starting from start_port"""
    port = start_port
    while port <= max_port:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('localhost', port)) != 0:
                return port
        port += 1
    raise RuntimeError(f"No available ports in range {start_port}-{max_port}")