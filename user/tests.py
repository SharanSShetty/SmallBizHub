import json
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from Business.models import Business, User
from user.models import CustomUser


class ChatbotViewTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create(
            username='alice',
            email='alice@example.com',
            password='secret123',
        )
        self.owner = User.objects.create(
            email='owner@example.com',
            password='ownerpass',
        )
        self.business = Business.objects.create(
            owner=self.owner,
            name='Alice Bakery',
            shop='Alice Bakery',
            mobile_number='9999999999',
            business_type='Bakery',
            business_address='MG Road',
            approval_status=True,
            description='Fresh breads and cakes every day.',
        )
        self.user.saved_businesses.add(self.business)
        session = self.client.session
        session['username'] = self.user.username
        session.save()

    def test_chatbot_page_loads_for_logged_in_user(self):
        response = self.client.get(reverse('chatbot'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Smart local business assistant')

    @patch('user.views.generate_chatbot_reply')
    def test_chatbot_message_returns_reply_and_stores_history(self, mock_reply):
        mock_reply.return_value = 'Alice Bakery is a good nearby option.'

        response = self.client.post(
            reverse('chatbot_message'),
            data=json.dumps({'message': 'Find me a bakery'}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['reply'], 'Alice Bakery is a good nearby option.')
        self.assertEqual(len(payload['history']), 2)
        self.assertEqual(payload['history'][0]['role'], 'user')
        self.assertEqual(payload['history'][1]['role'], 'model')

    def test_chatbot_message_requires_text(self):
        response = self.client.post(
            reverse('chatbot_message'),
            data=json.dumps({'message': '   '}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error'], 'Message cannot be empty.')
