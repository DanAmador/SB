<!-- One ticket's part of the second pass's prompt (`sbqueue.review_section`), repeated once per landed ticket inside
     templates/review-brief.md. Each {name} comes from the ticket, its commit and its worker's report; a line whose
     value is empty is dropped. This comment is not sent. A name the hub cannot fill is an error, so add none. -->
## The ticket

{ticket}

### The work

{second_try}
{commit_line}
Read the whole change with: {diff_cmd}

```diff
{diff}
```

{play}
### The worker's report ({report_path})

{report}

### This ticket's review file

Write your review to: {review_file}
