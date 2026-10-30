from datetime import date
from zoneinfo import ZoneInfo
from app.services.analytics_calc import compute_streak, percent_change, week_ranges

d = date  
print(compute_streak({d(2026,10,29), d(2026,10,28), d(2026,10,27), d(2026,10,24)}, d(2026,10,29)))  # current 3, longest 3
print(compute_streak({d(2026,10,28), d(2026,10,27)}, d(2026,10,29)))   # current 2, studied_today False (still alive)
print(compute_streak({d(2026,10,26)}, d(2026,10,29)))                    # current 0 (a full day was missed)
print(percent_change(90, 60), percent_change(5, 0), percent_change(5, None))  # 50.0 None None
print(week_ranges(d(2026,10,29), ZoneInfo("Africa/Nairobi")))            # week_start Mon 26 Oct, days_elapsed 4