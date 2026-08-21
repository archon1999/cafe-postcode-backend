from django.db import migrations


class Migration(migrations.Migration):
    """Preserve the already-applied production migration graph node.

    The original data operation was intentionally reverted in application
    code, but deployed Django migration names are immutable.  Keeping this
    node as a no-op prevents production history from diverging from source and
    gives future printing migrations a stable dependency.
    """

    dependencies = [('printing', '0011_remove_legacy_cashier_alias')]

    operations = []
