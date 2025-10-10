# Performance Optimizations for Render Free Tier

## Overview
This document outlines the optimizations made to maximize performance on Render's free tier (0.1 CPU, 512 MB RAM).

## Script Optimizations (`start_production.sh`)

### 1. Worker Configuration
- **1 Worker**: Single worker process to minimize memory usage
- **2 Threads**: Multiple threads per worker for handling concurrent requests
- **Why**: Multiple workers would consume too much memory (each worker loads the entire app)

### 2. Memory Optimizations
- **`--preload`**: Loads the application before forking workers (shared code = less memory)
- **`--worker-tmp-dir /dev/shm`**: Uses shared memory for worker heartbeat files (faster I/O)
- **`--max-requests 500`**: Recycles workers after 500 requests to prevent memory leaks
- **`--max-requests-jitter 50`**: Adds randomness to prevent all workers restarting simultaneously

### 3. Worker Class
- **`gthread`**: Best for I/O-bound applications like Dash (database queries, OAuth)
- Better than `sync` workers which block during I/O operations

### 4. Reduced Timeout
- **120 seconds** instead of 300: Faster timeout for unresponsive workers
- Prevents hung workers from consuming resources

## Application Optimizations

### 1. Dash Configuration
```python
compress=True  # Enable gzip compression for responses
update_title=None  # Disable title updates (reduces client-side JS)
```

### 2. Logging
- **Log Level: INFO**: Meaningful logs without debug noise
- **Structured Format**: Timestamped logs for monitoring
- **Key Events Logged**:
  - Application startup
  - Database initialization
  - User authentication/logout
  - OAuth errors
  - Health check failures

### 3. Health Check Endpoint
- **`/health`**: Monitor application health
- Quick database connectivity test
- Returns 200 (healthy) or 503 (unhealthy)

### 4. Session Optimization
- Cookies configured for security and compatibility
- Session data stored server-side (minimal memory per user)

## Database Optimizations

### Consider PostgreSQL on Render
If using Render's PostgreSQL:
1. **Connection Pooling**: Reuse database connections
2. **Efficient Queries**: DataService already caches results
3. **Indexes**: Ensure proper indexes on Year, Player columns

## Additional Recommendations

### 1. Environment Variables
Set these in Render dashboard for better performance:

```bash
# Gunicorn
WORKERS=1
THREADS=2
WORKER_CLASS=gthread
PRELOAD=true
LOG_LEVEL=info

# Python
PYTHONUNBUFFERED=1  # Don't buffer stdout (better logs)
PYTHONUTF8=1        # Enable UTF-8 mode

# Render auto-sleeps free apps - consider these for faster wake-up
WEB_CONCURRENCY=1   # Render uses this for worker count
```

### 2. Static Asset Optimization
- Dash already minifies JS/CSS in production
- Consider CDN for external assets if needed

### 3. Caching Strategy
- `DataService` already caches query results
- Cache is invalidated on data changes
- Consider Redis for multi-worker caching (if you scale up)

### 4. Monitor Memory Usage
Add to your dashboard:
```python
import psutil
import os

@server.route('/metrics')
def metrics():
    process = psutil.Process(os.getpid())
    return {
        'memory_mb': process.memory_info().rss / 1024 / 1024,
        'cpu_percent': process.cpu_percent(interval=1)
    }
```

## Performance Monitoring

### Key Metrics to Watch
1. **Response Time**: Should be < 2s for most requests
2. **Memory Usage**: Should stay under 450 MB (90% of limit)
3. **Error Rate**: Monitor logs for exceptions
4. **Health Check**: Use `/health` endpoint

### Render Logs
View logs in real-time:
```bash
# In Render dashboard, click "Logs" or use CLI
render logs -t
```

### What to Look For
- `Auth check - Authenticated: True` - Users logging in
- `User authenticated: user@email.com` - Successful OAuth
- `Health check failed` - Database issues
- Worker restart messages - Memory issues if frequent

## Expected Performance

### Cold Start (After Sleep)
- First request: 10-30 seconds
- App wakes from sleep on Render free tier

### Warm Application
- Page load: 1-3 seconds
- Callback execution: 100-500ms
- Database queries: 10-100ms (depending on complexity)

### Concurrent Users
- 1 worker, 2 threads = ~2 concurrent requests
- Additional requests queue (acceptable for small apps)
- Consider paid tier if > 5 concurrent users

## Troubleshooting

### High Memory Usage
1. Check for memory leaks in custom code
2. Reduce `MAX_REQUESTS` to recycle workers more often
3. Check if data service cache is too large

### Slow Response Times
1. Check database query performance
2. Enable more detailed logging (`LOG_LEVEL=debug`)
3. Monitor CPU usage (0.1 CPU is very limited)
4. Consider upgrading to paid tier

### Frequent Worker Restarts
1. Memory limit exceeded (512 MB)
2. Check logs for OOM (Out of Memory) errors
3. Reduce cache size or implement cache limits

## Scaling Beyond Free Tier

If you need better performance:
1. **Starter Instance ($7/mo)**: 0.5 CPU, 512 MB
   - Use `WORKERS=2` and `THREADS=4`
2. **Standard Instance**: 1 CPU, 2 GB RAM
   - Use `WORKERS=3` and `THREADS=4`

## Cost-Free Improvements

1. **Optimize Queries**: Review `data_service.py` for N+1 queries
2. **Lazy Loading**: Only load data when needed
3. **Pagination**: Limit rows returned in large tables
4. **Reduce Polling**: Increase `auth-check-interval` from 5s to 30s
5. **Client-Side Caching**: Store non-sensitive data in browser

## Summary

These optimizations make the app viable on Render's free tier for:
- ✅ Small teams (< 10 users)
- ✅ Low concurrent usage (< 3 simultaneous users)
- ✅ Non-critical applications (can tolerate cold starts)

For production use with more users, consider upgrading to a paid tier.
