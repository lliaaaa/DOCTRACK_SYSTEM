import click
from app import db
from app.models import User

def register_cli(app):
    @app.cli.command("create-admin")
    @click.argument("email")
    @click.argument("password")
    def create_admin(email, password):
        """Creates a default admin user."""
        try:
            if User.query.filter_by(email=email).first():
                click.echo(f"Admin user with email '{email}' already exists.")
                return

            # Create admin user
            new_admin = User(
                email=email,
                role="admin"  # Use 'role' instead of is_admin
            )
            new_admin.set_password(password)

            db.session.add(new_admin)
            db.session.commit()
            click.echo(f"Successfully created admin user: {email}")

        except Exception as e:
            db.session.rollback()
            click.echo(f"Error creating admin user: {e}", err=True)
