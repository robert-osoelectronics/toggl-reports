#!/bin/python
"""
Queries the Toggl Track API for activities from a preceding time period.
Formats the output into a nice ASCII output broken down by day and task, for
easy copying into a client's time reporting system.

TODO:
- combine API requests into a streamlined function?
- handle failed requests (check http return code, timeout, etc.)
- enable strict pylinting

"""

# pylint: disable=locally-disabled, redefined-outer-name, line-too-long, missing-function-docstring, invalid-name


import json
import configparser
import os
import sys
from argparse import ArgumentParser
from base64 import b64encode
from datetime import date, timedelta, datetime

import requests


def get_previous_date_range(
    num_days: int,
    end_date: date,
):
    """
    Get the dates for a range of days ending on a certain day.

    args:
    num_days -- the number of days in the range
    end_date -- the last day in the range

    returns:
    tuple of day strings, (starting day, ending day)
    """
    assert num_days >= 1
    assert isinstance(end_date, date)
    start_day = end_date - timedelta(days=num_days)
    return (start_day.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))


def query_toggl_workspaces(api_token: str):
    """
    Get the default workspace ID from Toggl (needed for other API calls).

    args:
    api_token -- your API token

    returns:
    default workspace ID reported from Toggl
    """
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
    """
    Get a list of active clients from Toggl.

    args:
    api_token -- Toggl API Token
    workspace_id -- your workspace ID (from query_toggl_workspaces())

    returns:
    a list of clients
    """
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
    """
    Prints an ASCII time report from the activities queried from Toggl.

    args:
    time_entries -- The json returned from the Toggl API call (query_toggl_time_entries())
    """

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

    for day, entries in entries_by_day.items():
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


def _enter_user_config():
    """
    Has the user enter their API key, and gets workspace ID from Toggl API.
    """
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
        _print_config(config)
        print("Enter Y to save, any other key to re-enter secrets:")
        done = input().lower() == "y"
    return config


def _print_config(config):
    """
    Prints a user config.

    args:
    config -- the user config to print
    """
    config_str = ""
    for section in config.sections():
        config_str += f"[{section}]\n"
        for name, value in config[section].items():
            config_str += f"{name} = {value}\n"
    print(config_str)


def _print_clients(clients):
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
        "-l", "--list_clients", help="List active clients.", action="store_true"
    )
    parser.add_argument(
        "-n",
        "--numdays",
        help="Number of days (including today) to include in report.",
        type=int,
        default=14,
    )
    args = parser.parse_args()

    config = configparser.ConfigParser()
    CONFIG_PATH = "secrets.ini"
    if os.path.exists(CONFIG_PATH):
        config.read(CONFIG_PATH)
    else:
        # No config file - prompt user for secrets
        print("No Config file found.")
        config = _enter_user_config()
        with open(CONFIG_PATH, "w", encoding="utf-8") as configfile:
            config.write(configfile)
    secrets = config["SECRETS"]

    api_token = secrets["api_token"]
    workspace_id = int(secrets["workspace_id"])
    clients = query_toggl_clients(api_token, workspace_id)

    if args.list_clients:
        _print_clients(clients)
        sys.exit(0)

    if args.client:
        client_name = args.client.lower()
        if client_name in clients:
            print(f"Filtering on client: {args.client}")
            client_ids = [clients[client_name]]
        else:
            print(f'Client "{args.client}" not found. Valid clients are:')
            _print_clients(clients)
            sys.exit(1)
    else:
        client_ids = []  # blank returns all clients

    time_entries = query_toggl_time_entries(
        api_token=api_token,
        workspace_id=workspace_id,
        client_ids=client_ids,
        date_range=get_previous_date_range(
            num_days=args.numdays, end_date=date.today()
        ),
    )
    generate_time_report(time_entries)
