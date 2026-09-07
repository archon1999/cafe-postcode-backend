from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('local_agents', '0009_localagentcommand_financial_operation_id_and_more')]
    operations = [migrations.AlterField(
        model_name='localagentmutationinbox', name='state',
        field=models.CharField(max_length=20, default='received', choices=[
            ('received', 'Received'), ('applied', 'Applied'), ('needs_review', 'Needs review'),
            ('resolved', 'Resolved without application'), ('conflict', 'Conflict'),
        ]),
    )]
