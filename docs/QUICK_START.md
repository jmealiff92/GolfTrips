# Quick Start Guide - Golf Trips Application

## Getting Started

### Running the Application

```bash
python3 dash_app_new.py
```

Then visit: http://localhost:8050

## New Features - Quick Reference

### 1. Managing Players

**Add a New Player:**
1. Navigate to **"Manage Players"**
2. Fill in:
   - Player Name
   - Year
   - Handicap Index (optional)
3. Click **"Add Player"**

**Update Player Handicap:**
1. Navigate to **"Manage Players"**
2. Select player from dropdown
3. Enter year and new handicap
4. Click **"Update Handicap"**

### 2. Managing Courses

**Add a New Course:**
1. Navigate to **"Manage Courses"**
2. Fill in:
   - Course Name
   - Par (e.g., 72)
   - Slope Rating (e.g., 130)
   - Course Rating (e.g., 73.5)
3. Click **"Add Course"**

**Edit Existing Course:**
1. Navigate to **"Manage Courses"**
2. Click on course row in table (selects it)
3. Fields auto-populate
4. Modify values
5. Click **"Update Course"**

### 3. Creating Matches (with Auto-Calculated Handicaps)

**Singles Match:**
1. Navigate to **"Add Match"**
2. Select:
   - Year (e.g., 2024)
   - Course (must exist in database)
   - Match Type: "Single"
   - Blue Player 1
   - Red Player 1
3. **Handicaps auto-calculate!**
4. Enter Day and Match Number
5. Click **"Add Match"**

**Fourball Match:**
1. Navigate to **"Add Match"**
2. Select:
   - Year
   - Course
   - Match Type: "Fourball"
   - All 4 players
3. **Handicaps auto-calculate!**
4. Click **"Add Match"**

### 4. Editing Match Results

**Update a Match Result:**
1. Navigate to **"Edit Matches"**
2. Click on match row to select it
3. Modal dialog opens
4. Select Result: Blue, Red, or Half
5. Enter Score (e.g., "3&2", "1UP", "A/S")
6. Click **"Save"**

## Summary

The new features provide:
- Complete player handicap management
- Course database with proper ratings
- Automatic WHS-compliant handicap calculations
- Easy match result editing
- Full audit trail of all data

Enjoy your golf trips!
