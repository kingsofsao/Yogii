proxy_pass http://api:8000;
proxy_http_version 1.1;
proxy_set_header Host $host;
# Overwrite (never append) so clients can't spoof their address for rate limiting.
proxy_set_header X-Forwarded-For $remote_addr;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_read_timeout 30s;
