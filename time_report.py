"""
TODO:
- command line args
- query API for workspace IDs and client IDs
- allow getting number of days previous to date (vs. having to be previous to a given weekday)

"""

import requests
import json
from base64 import b64encode
import calendar
from datetime import date, timedelta, datetime
import configparser

def get_last_weeks_date_range(
    num_weeks: int,
    day_of_week: int,
    previous_to: date,
):
    """
    Get the dates for a range of weeks ending on a day of week, previous to a given date.

    args:
    num_weeks -- the number of weeks in the range
    day_of_week -- the day the range should end on, e.g. calendar.FRIDAY
    previous_to -- the day that the date range should be before

    returns:
    tuple of day strings, (starting day, ending day)
    """
    assert num_weeks >= 1
    assert type(previous_to) is date
    assert day_of_week < 7
    dow_offset = (7 - (day_of_week - previous_to.weekday())) % 7
    end_day = previous_to - timedelta(days=dow_offset)
    start_day = end_day - timedelta(days=7 * num_weeks)
    return (start_day.strftime("%Y-%m-%d"), end_day.strftime("%Y-%m-%d"))


def query_toggl(
    api_token: str,
    workspace_id: int,
    client_ids: list,
    date_range: tuple,
):
    """
    Run a query against the Toggl time entry search API.

    args:
    api_token -- toggl API token
    workspace_id -- toggl workspace ID to query
    client_ids -- list of client IDs to filter on, empty [] to include all clients
    date_range -- tuple of dates to filter: (start_date, end_date)
    """
    assert len(date_range) == 2
    query = {
        "client_ids": client_ids,
        "start_date": date_range[0],
        "end_date": date_range[1],
        "order_by": "date",
    }
    data = requests.post(
        f"https://api.track.toggl.com/reports/api/v3/workspace/{workspace_id}/search/time_entries",
        json=query,
        headers={
            "content-type": "application/json",
            "Authorization": "Basic %s" % b64encode(bytes(api_token+":api_token", encoding='utf-8')).decode("ascii"),
        },
    )
    # print(data.text)
    # print(data.reason)
    # TODO: handle invalid responses
    return data.json()


def generate_time_report(time_entries: json):
    # Group entries by day
    entries_by_day = {}
    for entry in time_entries:
        # I think there is only ever one time entry per result here:
        assert len(entry["time_entries"]) == 1
        entry_detail = entry["time_entries"][0]

        start_date = datetime.strptime(
            entry_detail["start"], "%Y-%m-%dT%H:%M:%S%z"
        ).date()

        # Create a list for entries with this start date if it doesn't exist
        # and populate it with all time entries
        entries_by_day.setdefault(start_date, {"time_entries": []})
        entries_by_day[start_date]["time_entries"].append(
                {
                    "task": entry["description"],
                    "task_hours": round(entry_detail["seconds"] / 3600, 1),
                    "start_time": datetime.strptime(
                        entry_detail["start"], "%Y-%m-%dT%H:%M:%S%z"
                    ).time(),
                    "stop_time": datetime.strptime(
                        entry_detail["stop"], "%Y-%m-%dT%H:%M:%S%z"
                    ).time(),
                }
        )

    # Group entries by task and get total time per task and total per day
    for day in entries_by_day:
        entries_by_day[day]["task_totals"] = {}
        entries_by_day[day]["total_hours"] = 0
        for entry in entries_by_day[day]["time_entries"]:
            entries_by_day[day]["task_totals"].setdefault(entry["task"], 0)
            entries_by_day[day]["task_totals"][entry["task"]] += entry["task_hours"]
            entries_by_day[day]["total_hours"] += entry["task_hours"]

    for day in entries_by_day:
        data = entries_by_day[day]
        print("----")
        print(f'{day.strftime("%A %b %d %Y")}')
        print(f'Total Time: {data["total_hours"]:3.1f}')
        print(f'Task Summary:')
        for task in data["task_totals"]:
            print(f'- {task}: {data["task_totals"][task]:3.1f}hrs')
        print(f'\r\nTime Entries:')
        for entry in data["time_entries"]:
            print(f'{entry["task"]}, \
{entry["start_time"].strftime("%H:%M")}->{entry["stop_time"].strftime("%H:%M")}, \
{entry["task_hours"]:3.1f}hrs')
        print("\r\n\n")

def enter_user_config():
    done = False
    while(not done):
        config = configparser.ConfigParser()
        config["SECRETS"] = {}
        secret_cfg = config["SECRETS"]
        print("\r\nEnter Toggl API Token:")
        secret_cfg["api_token"] = input()
        print("Enter workspace ID:")
        secret_cfg["workspace_id"] = input()
        print("Enter default client IDs separated by commas:")
        ids =input().strip(' ').split(',') # unpack list to validate
        ids = ",".join(ids) # pack back into a list
        secret_cfg["client_ids"] = ids
        print(f"Entered config:")
        print_config(config)
        print("Enter Y to confirm, any other key to re-enter secrets:")
        done = (input().lower() == "y")
    return config

def print_config(config):
    config_str = ""
    for section in config.sections():
        config_str += f"[{section}]\n"
        for name, value in config[section].items():
            config_str += f"{name} = {value}\n"
    print(config_str)

if __name__ == "__main__":
    config = configparser.ConfigParser()
    try:
        config.read("secrets.ini")
    except FileNotFoundError:
        # No config file - prompt user for secrets
        print("No Config file found.")
        config = enter_user_config()
        with open("secrets.ini", "w") as configfile:
            config.write(configfile)
    secrets = config["SECRETS"]

    previous_to_day = date.today()

    time_entries = query_toggl(
        api_token=secrets["api_token"],
        workspace_id=int(secrets["workspace_id"]),
        client_ids=[int(i) for i in secrets["client_ids"].split(",")],
        date_range=get_last_weeks_date_range(
            num_weeks=2, day_of_week=calendar.FRIDAY, previous_to=previous_to_day
        )
    )
    generate_time_report(time_entries)
