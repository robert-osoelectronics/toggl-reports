"""
TODO:
- allow getting number of days previous to date (vs. having to be previous to a given weekday)
- combine API requests into a streamlined function?
- handle failed requests (check http return code, timeout, etc.)
- enable strict pylinting

"""

# pylint: disable=redefined-outer-name, line-too-long, missing-function-docstring


import json
import calendar
import configparser
import os
import sys
from argparse import ArgumentParser
from base64 import b64encode
from datetime import date, timedelta, datetime

import requests


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
    assert isinstance(previous_to, date)
    assert day_of_week < 7
    dow_offset = (7 - (day_of_week - previous_to.weekday())) % 7
    end_day = previous_to - timedelta(days=dow_offset)
    start_day = end_day - timedelta(days=7 * num_weeks)
    return (start_day.strftime("%Y-%m-%d"), end_day.strftime("%Y-%m-%d"))


def query_toggl_workspaces(api_token: str):

    data = requests.get(
        "https://api.track.toggl.com/api/v9/me",
        headers={
            "content-type": "application/json",
            "Authorization": f'Basic {b64encode(bytes(api_token + ":api_token", encoding="utf-8")).decode("ascii"):s}',
        },
    )
    return data.json()["default_workspace_id"]


def query_toggl_time_entries(
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
            "Authorization": f'Basic {b64encode(bytes(api_token + ":api_token", encoding="utf-8")).decode("ascii"):s}',
        },
    )
    return data.json()


def query_toggl_clients(
    api_token: str,
    workspace_id: int,
):

    data = requests.get(
        f"https://api.track.toggl.com/api/v9/workspaces/{workspace_id}/clients",
        headers={
            "content-type": "application/json",
            "Authorization": f'Basic {b64encode(bytes(api_token + ":api_token", encoding="utf-8")).decode("ascii"):s}',
        },
    )
    clients = {}
    for client in data.json():
        clients[client["name"].lower()] = client["id"]
    return clients


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
    for day, entries in entries_by_day.items():
        entries["task_totals"] = {}
        entries["total_hours"] = 0
        for entry in entries["time_entries"]:
            entries["task_totals"].setdefault(entry["task"], 0)
            entries["task_totals"][entry["task"]] += entry["task_hours"]
            entries["total_hours"] += entry["task_hours"]

    for day, entries in entries_by_day:
        print("----")
        print(f'{day.strftime("%A %b %d %Y")}')
        print(f'Total Time: {entries["total_hours"]:3.1f}')
        print("Task Summary:")
        for task in entries["task_totals"]:
            print(f'- {task}: {entries["task_totals"][task]:3.1f}hrs')
        print("\r\nTime Entries:")
        for entry in entries["time_entries"]:
            print(
                f'{entry["task"]}, \
{entry["start_time"].strftime("%H:%M")}->{entry["stop_time"].strftime("%H:%M")}, \
{entry["task_hours"]:3.1f}hrs'
            )
        print("\r\n\n")


def enter_user_config():
    done = False
    while not done:
        config = configparser.ConfigParser()
        config["SECRETS"] = {}
        secret_cfg = config["SECRETS"]
        print("\r\nEnter Toggl API Token:")
        api_token = input()
        secret_cfg["api_token"] = api_token
        print("Querying workspace ID... ")
        workspace_id = query_toggl_workspaces(api_token)
        print(f"Got workspace ID: {workspace_id}")
        secret_cfg["workspace_id"] = str(workspace_id)
        print("Entered config:")
        print_config(config)
        print("Enter Y to save, any other key to re-enter secrets:")
        done = input().lower() == "y"
    return config


def print_config(config):
    config_str = ""
    for section in config.sections():
        config_str += f"[{section}]\n"
        for name, value in config[section].items():
            config_str += f"{name} = {value}\n"
    print(config_str)


def print_clients(clients):
    for c in clients:
        print(c)


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument(
        "-c",
        "--client",
        help="Client name to filter on. Run with --list_clients to list options.",
    )
    parser.add_argument(
        "-l", "--list_clients", help="List active clients", action="store_true"
    )
    args = parser.parse_args()

    config = configparser.ConfigParser()
    CONFIG_PATH = "secrets.ini"
    if os.path.exists(CONFIG_PATH):
        config.read(CONFIG_PATH)
    else:
        # No config file - prompt user for secrets
        print("No Config file found.")
        config = enter_user_config()
        with open(CONFIG_PATH, "w", encoding="utf-8") as configfile:
            config.write(configfile)
    secrets = config["SECRETS"]

    previous_to_day = date.today()

    api_token = secrets["api_token"]
    workspace_id = int(secrets["workspace_id"])
    clients = query_toggl_clients(api_token, workspace_id)

    if args.list_clients:
        print_clients(clients)
        sys.exit(0)

    if args.client:
        client_name = args.client.lower()
        if client_name in clients:
            print(f"Filtering on client: {args.client}")
            client_ids = [clients[client_name]]
        else:
            print(f'Client "{args.client}" not found. Valid clients are:')
            print_clients(clients)
            sys.exit(1)
    else:
        client_ids = []  # blank returns all clients

    time_entries = query_toggl_time_entries(
        api_token=api_token,
        workspace_id=workspace_id,
        client_ids=client_ids,
        date_range=get_last_weeks_date_range(
            num_weeks=2, day_of_week=calendar.FRIDAY, previous_to=previous_to_day
        ),
    )
    generate_time_report(time_entries)
