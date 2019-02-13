from bitcoin.core import COIN
from flask import request, render_template
from flask_admin import BaseView, expose

from node_launcher.logging import log
from node_launcher.node_set import NodeSet
from website.forms.request_capacity_form import RequestCapacityForm
from website.utilities.cache.cache import get_latest


class RequestCapacityView(BaseView):

    @expose('/')
    def index(self):
        form = RequestCapacityForm()
        price = get_latest('usd_price')
        last_price = price['last']
        price_per_sat = last_price/COIN
        fee_estimates = get_latest('fee_estimate')

        fee_estimate_choices = []
        previous_estimate = 0
        for fee_estimate in fee_estimates:
            estimated_fee_per_byte = fee_estimate['conservative']['feerate']
            if estimated_fee_per_byte == previous_estimate:
                continue
            previous_estimate = estimated_fee_per_byte
            select_label_time_estimate = fee_estimate['label'].replace('_', ' ').capitalize()
            if estimated_fee_per_byte > 1:
                select_label = f'{select_label_time_estimate} ({estimated_fee_per_byte} sats per byte)'
            else:
                select_label = f'{select_label_time_estimate} (1 sat per byte)'
            select_value = estimated_fee_per_byte
            fee_estimate_choices.append((select_value, select_label))
        form.fee_rate.choices = fee_estimate_choices
        form.capacity.choices = []
        capacity_choices = [500000, 1000000, 2000000, 5000000, 16777215]
        for capacity_choice in capacity_choices:
            form.capacity.choices.append((capacity_choice, f'{capacity_choice:,}'))

        form.minimum_time_open.choices = [
                (0, 'One week free'),
                (2, 'One month 2%'),
                (10, 'Six months 10%'),
                (18, 'One year 18%')
        ]
        node_set = NodeSet()
        address = node_set.lnd_client.get_new_address()
        return render_template('request_capacity.html',
                               form=form,
                               address=address,
                               price_per_sat=price_per_sat)

    @expose('/process_request', methods=['GET', 'POST'])
    def process_request(self):
        if request.method == 'POST':
            data = request.form
            log.info('request-capacity.process_request POST', data=data)

        node_set = NodeSet()
        payment_request = node_set.lnd_client.create_invoice(
            value=100,
            memo='Capacity request'
        ).payment_request
        uri = ':'.join(['lightning', payment_request])

        return render_template('payment_request.html',
                               payment_request=payment_request,
                               uri=uri)