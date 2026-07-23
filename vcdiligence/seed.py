from vcdiligence.database import SessionLocal, Organization, User, init_db
from vcdiligence.security import hash_password

def seed_database():
    init_db()
    session = SessionLocal()
    try:
        # Check if organizations exist, if not create them
        dealscout_org = session.query(Organization).filter_by(company_name="DealScout Capital").first()
        if not dealscout_org:
            dealscout_org = Organization(id=1, company_name="DealScout Capital", logo_path=None)
            session.add(dealscout_org)
            session.commit()
            print("Seeded organization 'DealScout Capital'")
        else:
            print("'DealScout Capital' already exists")

        angel_org = session.query(Organization).filter_by(company_name="Angel Syndicate LLC").first()
        if not angel_org:
            angel_org = Organization(id=2, company_name="Angel Syndicate LLC", logo_path=None)
            session.add(angel_org)
            session.commit()
            print("Seeded organization 'Angel Syndicate LLC'")
        else:
            print("'Angel Syndicate LLC' already exists")

        # Seed Users
        admin_user = session.query(User).filter_by(email="admin@dealscout.ai").first()
        if not admin_user:
            admin_user = User(
                email="admin@dealscout.ai",
                hashed_password=hash_password("adminpassword"),
                role="administrador",
                organization_id=1
            )
            session.add(admin_user)
            print("Seeded admin@dealscout.ai")

        analyst_user = session.query(User).filter_by(email="analyst@dealscout.ai").first()
        if not analyst_user:
            analyst_user = User(
                email="analyst@dealscout.ai",
                hashed_password=hash_password("analystpassword"),
                role="analista",
                organization_id=1
            )
            session.add(analyst_user)
            print("Seeded analyst@dealscout.ai")

        syndicate_user = session.query(User).filter_by(email="syndicate@angel.co").first()
        if not syndicate_user:
            syndicate_user = User(
                email="syndicate@angel.co",
                hashed_password=hash_password("syndicatepassword"),
                role="analista",
                organization_id=2
            )
            session.add(syndicate_user)
            print("Seeded syndicate@angel.co")

        session.commit()
        print("Database seeding completed.")
    except Exception as e:
        session.rollback()
        print(f"Error seeding database: {str(e)}")
    finally:
        session.close()

if __name__ == "__main__":
    seed_database()
