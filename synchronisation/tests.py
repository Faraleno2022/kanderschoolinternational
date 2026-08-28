import json

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from eleves.models import Ecole
from utilisateurs.models import Profil


class SynchronisationApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='adminsync', password='secret123')
        self.ecole = Ecole.objects.create(
            nom='Ecole Test',
            adresse='Conakry',
            telephone='+224600000000',
            directeur='Direction',
            etat='VALIDE',
        )
        profil, _ = Profil.objects.get_or_create(user=self.user)
        profil.role = 'ADMIN'
        profil.ecole = self.ecole
        profil.save(update_fields=['role', 'ecole'])
        self.client = Client()

    def test_health_endpoint(self):
        response = self.client.get(reverse('synchronisation:health'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ok'])

    def test_register_device_and_push_change(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('synchronisation:register_device'),
            data=json.dumps({'nom': 'Poste direction'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()

        response = self.client.post(
            reverse('synchronisation:push'),
            data=json.dumps({
                'changes': [
                    {
                        'model': 'eleves.Ecole',
                        'object_uuid': str(self.ecole.sync_uuid),
                        'operation': 'UPDATE',
                        'payload': {
                            'sync_uuid': str(self.ecole.sync_uuid),
                            'nom': 'Ecole Test Sync',
                            'adresse': 'Conakry',
                            'telephone': '+224600000000',
                            'directeur': 'Direction',
                            'etat': 'VALIDE',
                        },
                    }
                ]
            }),
            content_type='application/json',
            HTTP_X_SYNC_DEVICE=data['device_id'],
            HTTP_X_SYNC_TOKEN=data['sync_token'],
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['accepted_count'], 1)

    def test_register_device_with_admin_token_and_pull_other_device_changes(self):
        from django.test import override_settings

        with override_settings(MYSCHOOL_SYNC_ADMIN_TOKEN='bootstrap-secret'):
            response = self.client.post(
                reverse('synchronisation:register_device'),
                data=json.dumps({'nom': 'Poste 1', 'ecole_id': self.ecole.id}),
                content_type='application/json',
                HTTP_X_SYNC_ADMIN_TOKEN='bootstrap-secret',
            )
        self.assertEqual(response.status_code, 201)
        device_one = response.json()

        with override_settings(MYSCHOOL_SYNC_ADMIN_TOKEN='bootstrap-secret'):
            response = self.client.post(
                reverse('synchronisation:register_device'),
                data=json.dumps({'nom': 'Poste 2', 'ecole_id': self.ecole.id}),
                content_type='application/json',
                HTTP_X_SYNC_ADMIN_TOKEN='bootstrap-secret',
            )
        self.assertEqual(response.status_code, 201)
        device_two = response.json()

        response = self.client.post(
            reverse('synchronisation:push'),
            data=json.dumps({
                'changes': [
                    {
                        'model': 'eleves.Ecole',
                        'object_uuid': str(self.ecole.sync_uuid),
                        'operation': 'UPDATE',
                        'payload': {
                            'sync_uuid': str(self.ecole.sync_uuid),
                            'nom': 'Ecole Test Poste 1',
                            'adresse': 'Conakry',
                            'telephone': '+224600000000',
                            'directeur': 'Direction',
                            'etat': 'VALIDE',
                        },
                    }
                ]
            }),
            content_type='application/json',
            HTTP_X_SYNC_DEVICE=device_one['device_id'],
            HTTP_X_SYNC_TOKEN=device_one['sync_token'],
        )
        self.assertEqual(response.status_code, 200)

        response = self.client.get(
            reverse('synchronisation:pull'),
            HTTP_X_SYNC_DEVICE=device_two['device_id'],
            HTTP_X_SYNC_TOKEN=device_two['sync_token'],
        )
        self.assertEqual(response.status_code, 200)
        # Le second poste recoit la modification poussee par le premier, et
        # desormais aussi la creation de l'ecole faite sur le serveur : un
        # changement ne circule plus seulement s'il vient d'un autre poste.
        changements = [
            (item['model_label'], item['operation'])
            for item in response.json()['changes']
        ]
        self.assertIn(('eleves.Ecole', 'UPDATE'), changements)
        self.assertIn(('eleves.Ecole', 'CREATE'), changements)
