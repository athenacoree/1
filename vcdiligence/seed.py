import secrets
from vcdiligence.database import SessionLocal, Organization, User, init_db
from vcdiligence.security import hash_password

def seed_database():
    init_db()
    session = SessionLocal()
    try:
        # Check if organizations exist, if not create them within same transaction
        dealscout_org = session.query(Organization).filter_by(company_name="DealScout Capital").first()
        if not dealscout_org:
            dealscout_org = Organization(id=1, company_name="DealScout Capital", logo_path=None)
            session.add(dealscout_org)
            print("Preparing to seed organization 'DealScout Capital'...")
        else:
            print("'DealScout Capital' already exists")

        angel_org = session.query(Organization).filter_by(company_name="Angel Syndicate LLC").first()
        if not angel_org:
            angel_org = Organization(id=2, company_name="Angel Syndicate LLC", logo_path=None)
            session.add(angel_org)
            print("Preparing to seed organization 'Angel Syndicate LLC'...")
        else:
            print("'Angel Syndicate LLC' already exists")

        # Seed Users
        admin_user = session.query(User).filter_by(email="admin@dealscout.ai").first()
        if not admin_user:
            admin_pw = secrets.token_urlsafe(16)
            admin_user = User(
                email="admin@dealscout.ai",
                hashed_password=hash_password(admin_pw),
                role="administrador",
                organization_id=1
            )
            session.add(admin_user)
            print(f"Seeded admin@dealscout.ai with secure password: {admin_pw}")

        analyst_user = session.query(User).filter_by(email="analyst@dealscout.ai").first()
        if not analyst_user:
            analyst_pw = secrets.token_urlsafe(16)
            analyst_user = User(
                email="analyst@dealscout.ai",
                hashed_password=hash_password(analyst_pw),
                role="analista",
                organization_id=1
            )
            session.add(analyst_user)
            print(f"Seeded analyst@dealscout.ai with secure password: {analyst_pw}")

        syndicate_user = session.query(User).filter_by(email="syndicate@angel.co").first()
        if not syndicate_user:
            syndicate_pw = secrets.token_urlsafe(16)
            syndicate_user = User(
                email="syndicate@angel.co",
                hashed_password=hash_password(syndicate_pw),
                role="analista",
                organization_id=2
            )
            session.add(syndicate_user)
            print(f"Seeded syndicate@angel.co with secure password: {syndicate_pw}")

        session.commit()
        print("Database seeding completed.")
    except Exception as e:
        session.rollback()
        print(f"Error seeding database: {str(e)}")
        raise e
    finally:
        session.close()

if __name__ == "__main__":
    seed_database()
