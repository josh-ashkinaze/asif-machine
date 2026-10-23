import os
from datetime import timezone
from zoneinfo import ZoneInfo

from bson import ObjectId
from dotenv import load_dotenv
from pymongo import MongoClient


# ######################################
# Functions for calling MONGODB database
# ######################################


def _no_database(database_url, what):
    """
    True when no Mongo connection string is configured.

    The app is usable without a database: you can write and get suggestions, but
    nothing is persisted. This keeps local setup to one API key. Set
    MONGO_WORKING_STAGE_URL (local) or MONGO_URL (deployed) to save data.
    """
    if not database_url:
        print(f"NO MONGO URL SET -- skipping save of {what}. Nothing is being recorded.")
        return True
    return False


def insert_user_data_to_database(database_name, database_url, user_info):
    """
    Connects to the specified MongoDB database and inserts a predefined item into the 'user-data' collection.

    Parameters:
    database_name (str): The name of the database to connect to.
    database_url (str): the database to connect to. Name of env variable that hold the endpoint
    user_info: user_info object from current session. (session["user_info"])
    Returns:
    InsertOneResult: The result of the insert operation.
    """
    if _no_database(database_url, "user data"):
        return None
    print("SENDING USER SESSION DATA TO DB")
    print("Connecting to endpoint", database_url)
    client = MongoClient(database_url)  # Connect to endpoint
    print("Selecting the  databse")
    dbname = client[database_name]  # Select the database. Create if not exist
    print("Selecting the collection ")
    collection_name = dbname["user-data"]  # Select the collection
    print("Inserting the user info")
    collection_name.insert_one(user_info)


def insert_error_log(database_name, database_url, doc):
    """Insert a document into the 'error-log' collection. Fails silently."""
    if not database_url:
        return None
    try:
        client = MongoClient(database_url)
        client[database_name]["error-log"].insert_one(doc)
        client.close()
    except Exception:
        pass


def insert_journal_data_to_database(database_name, database_url, journal_data):
    """
    Connects to the specified MongoDB database and inserts a predefined item into the 'journal-data' collection.

    Parameters:
    database_name (str): The name of the database to connect to.
    database_url (str): the database to connect to. Name of env variable that hold the endpoint
    journal_data: journal_data object from current session. (session["journal_data"])
    Returns:
    InsertOneResult: The result of the insert operation.
    """
    if _no_database(database_url, "journal data"):
        return None
    print("SENDING JOURNAL DATA TO DB")
    print("Connecting to endpoint", database_url)
    client = MongoClient(database_url)  # Connect to endpoint
    print("Selecting the  databse")
    dbname = client[database_name]  # Select the database. Create if not exist
    print("Selecting the collection ")
    collection_name = dbname["journal-data"]  # Select the collection
    print("Inserting the journal data")
    collection_name.insert_one(journal_data)


def drop_database(database_name, database_url):
    """
    Connects to the specified MongoDB database and drops it.

    Parameters:
    database_name (str): The name of the database to drop.
    database_url (str): the database to connect to. Name of env variable that hold the endpoint
    """
    print("DROPPING DATABASE")
    print("Connecting to endpoint", database_url)
    client = MongoClient(database_url)  # Connect to endpoint
    print(f"Dropping the database: {database_name}")
    client.drop_database(database_name)


def remove_collections(database_name, database_url, collections):
    """
    Connects to the specified MongoDB database and removes the specified collections.

    Parameters:
    database_name (str): The name of the database to connect to.
    database_url (str): the database to connect to. Name of env variable that hold the endpoint
    collections (list): A list of collection names to remove.
    """
    print("REMOVING COLLECTIONS")
    print("Connecting to endpoint", database_url)
    client = MongoClient(database_url)  # Connect to endpoint
    dbname = client[database_name]  # Select the database
    for collection_name in collections:
        print(f"Removing collection: {collection_name}")
        dbname[collection_name].drop()  #


def retrieve_database_data(branch_name, data_collection, event_id=None, start_date=None, end_date=None):
    """
    Retrieve data from MongoDB including insertion timestamps for specified branch and collection.

    Args:
        branch_name (str): Name of the branch ('working', 'staging', or 'production')
        data_collection (str): Name of the MongoDB collection to query
        event_id (str, optional): Filter by event key (e.g. 'event_placebo_synesthesia').
            Applies to user-data collection only. If None, returns all documents.
        start_date (datetime, optional): Include only docs inserted on or after this date (UTC midnight).
        end_date (datetime, optional): Include only docs inserted before the start of the day after this date.

    Returns:
        list: List of documents with insertion timestamps
    """
    load_dotenv()
    if branch_name == "working":
        database_url = os.getenv("MONGO_WORKING_STAGE_URL")
    elif branch_name == "staging":
        database_url = os.getenv("MONGO_STAGING_URL")
    elif branch_name == "production":
        database_url = os.getenv("MONGO_PRODUCTION_URL")
    else:
        raise ValueError("Selected branch does not have a mongodb instance")
    client = MongoClient(database_url)
    dbname = client["user"]
    collection_name = dbname[data_collection]

    query = {"event_id": event_id} if event_id else {}

    if start_date or end_date:
        id_filter = {}
        if start_date:
            id_filter["$gte"] = ObjectId.from_datetime(start_date.replace(tzinfo=timezone.utc))
        if end_date:
            from datetime import timedelta
            next_day = end_date.replace(tzinfo=timezone.utc) + timedelta(days=1)
            id_filter["$lt"] = ObjectId.from_datetime(next_day)
        query["_id"] = id_filter

    all_items = collection_name.find(query)
    documents = []

    # get datetime of insertion
    for doc in all_items:
        insertion_time = doc["_id"].generation_time.astimezone(ZoneInfo("America/New_York"))
        doc["est_ts"] = insertion_time
        documents.append(doc)

    client.close()
    return documents
