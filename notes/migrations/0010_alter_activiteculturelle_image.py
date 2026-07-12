from django.db import migrations, models

import eleves.validators


class Migration(migrations.Migration):

    dependencies = [
        ('notes', '0009_activiteculturelle'),
    ]

    operations = [
        migrations.AlterField(
            model_name='activiteculturelle',
            name='image',
            field=models.ImageField(
                help_text="Photo de l'activité (max 15 Mo)",
                upload_to='activites_culturelles/',
                validators=[eleves.validators.validate_photo_size],
                verbose_name='Image',
            ),
        ),
    ]
