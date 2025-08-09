import pytest, asyncio
from tests.API.User.user_client import UserClient
from motor.motor_asyncio import AsyncIOMotorClient


@pytest.fixture(scope="session")
def api_client():
    return UserClient()


@pytest.fixture(scope="function")
def clean_all_users():
    emails_to_clean = []

    async def cleanup_user(email):
        emails_to_clean.append(email)

    yield cleanup_user

    if emails_to_clean:
        client = AsyncIOMotorClient("mongodb://localhost:27018/?directConnection=true")
        db = client["8_films"]

        async def run_cleanup():
            for email in emails_to_clean:
                await db.users.delete_one({"email": email})

        asyncio.run(run_cleanup())
        client.close()


@pytest.fixture(scope="function")
def prepare_db_without_basic_plan():
    basic_plan = None

    async def setup():
        nonlocal basic_plan
        client = AsyncIOMotorClient("mongodb://localhost:27018/?directConnection=true")
        db = client["8_films"]

        basic_plan = await db.subscriptionplans.find_one({"price": 0})
        if basic_plan:
            await db.subscriptionplans.delete_one({"price": 0})
        client.close()

    async def cleanup():
        nonlocal basic_plan
        client = AsyncIOMotorClient("mongodb://localhost:27018/?directConnection=true")
        db = client["8_films"]
        if basic_plan:
            basic_plan.pop("_id", None)
            await db.subscriptionplans.insert_one(basic_plan)
        client.close()

    asyncio.run(setup())
    yield
    asyncio.run(cleanup())


@pytest.fixture(scope="function")
def registered_user_in_db(api_client):
    registered_emails = []

    async def create_user(user_data):
        response = await api_client.register_user(user_data)
        assert response.status_code == 201
        registered_emails.append(user_data["email"])
        return user_data, response

    yield create_user
    if registered_emails:
        client = AsyncIOMotorClient("mongodb://localhost:27018/?directConnection=true")
        db = client["8_films"]

        async def run_cleanup():
            for email in registered_emails:
                await db.users.delete_one({"email": email})

        asyncio.run(run_cleanup())
        client.close()
