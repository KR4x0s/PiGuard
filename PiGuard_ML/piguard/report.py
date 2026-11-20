"""Export observation coverage and review burden without assuming ground truth."""
import argparse
import json
import sqlite3
import time
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--state',type=Path,required=True)
    p.add_argument('--days',type=int,default=7)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if not 1<=args.days<=14:
        p.error('Detailed alert retention supports 1–14 days')
    if args.output.exists():
        p.error('Use a new output path')
    db=sqlite3.connect(args.state.resolve().as_uri()+'?mode=ro',uri=True)
    db.row_factory=sqlite3.Row
    # Report complete UTC days only: partial today must not dilute daily burden.
    end=int(time.time()//86400)*86400
    start=end-args.days*86400
    counts=[dict(r) for r in db.execute("SELECT day,key,count FROM daily WHERE day>=date(?,'unixepoch') AND day<date(?,'unixepoch') ORDER BY day,key",(start,end))]
    reviews=[dict(r) for r in db.execute('SELECT day,review_status,count(*) alerts,sum(query_count) queries FROM alerts WHERE first_seen>=? AND first_seen<? GROUP BY day,review_status ORDER BY day',(start,end))]
    observed_days={r['day'] for r in counts if r['key']=='queries_observed'}
    benign=sum(r['alerts'] for r in reviews if r['review_status']=='benign')
    health=db.execute("SELECT value FROM meta WHERE key='health'").fetchone()
    report={'period_start_utc_epoch':start,'period_end_utc_epoch':end,'requested_days':args.days,
            'days_with_observed_queries':len(observed_days),'daily_counters':counts,'review_summary':reviews,
            'benign_alerts_per_observed_day':benign/len(observed_days) if observed_days else None,
            'latest_health':json.loads(health[0]) if health else {},
            'limitations':['Unreviewed traffic has no ground-truth label.',
                'Days with queries do not establish uninterrupted coverage.',
                'No-query days are not automatically counted as healthy or quiet.',
                'Reviewed benign alerts count domain/model/day groups, not malware incidence.']}
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':
    main()
