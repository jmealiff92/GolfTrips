# Render Deployment Guide

## Quick Setup

### 1. Push to GitHub
```bash
git add .
git commit -m "Production optimizations for Render"
git push origin main
```

### 2. Create Render Service
1. Go to https://render.com/
2. Click "New +" → "Web Service"
3. Connect your GitHub repository
4. Configure:
   - **Name**: `golf-trips`
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `./start_production.sh`
   - **Instance Type**: `Free`

### 3. Set Environment Variables
In Render Dashboard → Environment:

```bash
# Required - OAuth Configuration
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret
SECRET_KEY=your-random-secret-key-here

# Optional - Admin Access Control
ADMIN_EMAILS=admin1@example.com,admin2@example.com

# Optional - Performance Tuning
WORKERS=1
THREADS=2
LOG_LEVEL=info
PRELOAD=true

# Optional - Python Settings
PYTHONUNBUFFERED=1
PYTHONUTF8=1

# Optional - Database (if using PostgreSQL)
DATABASE_URL=postgresql://user:pass@host:5432/dbname
```

### 4. Google OAuth Setup
Update your Google Cloud Console:
1. Go to https://console.cloud.google.com/
2. Select your project
3. Navigate to "APIs & Services" → "Credentials"
4. Edit your OAuth 2.0 Client ID
5. Add Authorized redirect URIs:
   ```
   https://your-app-name.onrender.com/authorize
   ```
6. Add Authorized JavaScript origins:
   ```
   https://your-app-name.onrender.com
   ```

## Monitoring

### View Logs
```bash
# In Render dashboard
Click "Logs" tab for real-time logs

# Look for these key messages:
✅ "Application initialization complete"
✅ "User authenticated: user@email.com"
⚠️  "OAuth error" - Check OAuth configuration
❌ "Health check failed" - Database issues
```

### Health Check
```bash
# Test health endpoint
curl https://your-app-name.onrender.com/health

# Expected response
{"status": "healthy", "database": "connected"}
```

### Key Metrics
Monitor these in logs:
- **Startup time**: Should be < 30s
- **Memory usage**: Should stay under 450 MB
- **Auth checks**: Every 30s per active user
- **Worker restarts**: Should be infrequent (every ~500 requests)

## Performance Tips

### 1. Keep App Warm (Free Tier Sleeps After 15 min)
Use a service like:
- **UptimeRobot** (free): https://uptimerobot.com/
- **Cron-job.org** (free): https://cron-job.org/

Configure to ping your health endpoint every 14 minutes:
```
https://your-app-name.onrender.com/health
```

### 2. Optimize Cold Starts
- Use `--preload` flag (already configured)
- Keep dependencies minimal
- Consider upgrading to paid tier ($7/mo) for no sleep

### 3. Monitor Performance
Check Render metrics:
- Response time
- Memory usage
- CPU usage (will max at 0.1 on free tier)

## Troubleshooting

### App Won't Start
1. Check logs for errors
2. Verify all required env vars are set
3. Test locally: `./start_production.sh`
4. Check build command succeeded

### OAuth Not Working
1. Verify redirect URI in Google Console
2. Check `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`
3. Ensure using HTTPS (Render provides this automatically)
4. Check logs for "OAuth error" messages

### Database Connection Errors
1. Check `DATABASE_URL` format
2. Verify PostgreSQL service is running
3. Check database allows connections from Render
4. Test `/health` endpoint

### Memory Issues (App Crashes)
1. Check logs for OOM (Out of Memory) errors
2. Reduce `MAX_REQUESTS` to recycle workers more often
3. Consider upgrading to paid tier (2 GB RAM)

### Slow Performance
1. **Expected on free tier**: 0.1 CPU is very limited
2. Cold starts take 10-30 seconds
3. Use uptime monitor to keep app warm
4. Consider upgrading for better performance

## Cost Optimization

### Free Tier Limits
- ✅ 750 hours/month (enough for 1 app running 24/7)
- ✅ 100 GB bandwidth/month
- ✅ Automatic HTTPS
- ⚠️  App sleeps after 15 min inactivity
- ⚠️  0.1 CPU (very limited)
- ⚠️  512 MB RAM

### When to Upgrade ($7/month Starter)
- More than 5 concurrent users
- Need faster response times
- Want no sleep (instant access)
- 0.5 CPU, 512 MB RAM

### Alternative Free Options
- **Railway**: 500 hours/month (less than Render)
- **Fly.io**: More resources but complex setup
- **Heroku**: No longer has free tier

## Security Checklist

- ✅ Use strong `SECRET_KEY` (generate with `openssl rand -hex 32`)
- ✅ Enable `SESSION_COOKIE_HTTPONLY` (already configured)
- ✅ Use HTTPS (Render provides automatically)
- ✅ Restrict `ADMIN_EMAILS` to trusted users
- ✅ Keep dependencies updated
- ✅ Don't commit `.env` file (use Render env vars)

## Backup Strategy

### Database Backups
If using Render PostgreSQL:
1. Render automatically backs up paid databases
2. Free databases are not backed up
3. Consider periodic exports:
   ```bash
   pg_dump $DATABASE_URL > backup.sql
   ```

### Code Backups
- GitHub is your backup
- Tag releases: `git tag v1.0.0 && git push --tags`

## Support

### Render Support
- Free tier: Community support only
- Paid tier: Email support
- Discord: https://discord.gg/render

### Application Issues
- Check logs first
- Review `PERFORMANCE_OPTIMIZATIONS.md`
- Review `SESSION_FIX.md` for auth issues

## Example Deployment Flow

```bash
# 1. Test locally
./start_production.sh

# 2. Commit and push
git add .
git commit -m "Ready for production"
git push origin main

# 3. Deploy on Render
# (Render auto-deploys on push if configured)

# 4. Monitor logs
# Check Render dashboard logs

# 5. Test
# Visit https://your-app-name.onrender.com
# Try logging in
# Check /health endpoint

# 6. Set up monitoring
# Configure UptimeRobot to ping /health every 14 min
```

## Success Indicators

After deployment, you should see:
1. ✅ App accessible at your Render URL
2. ✅ HTTPS working (automatic)
3. ✅ Login working (OAuth flow)
4. ✅ Health check returning 200
5. ✅ Logs showing successful startups
6. ✅ No repeated worker restarts
7. ✅ Memory usage < 450 MB

## Next Steps

1. **Set up uptime monitoring** to prevent sleep
2. **Monitor logs** for first few days
3. **Test with real users**
4. **Consider upgrade** if performance is insufficient
5. **Set up database backups** if using PostgreSQL

---

**Note**: Free tier is suitable for development and small teams. For production use with more users, consider upgrading to a paid tier.
