import time

from PySide2 import QtWidgets
from PySide2.QtCore import QThreadPool
from PySide2.QtWidgets import QInputDialog, QLineEdit, QErrorMessage
# noinspection PyProtectedMember
from grpc._channel import _Rendezvous

from node_launcher.constants import keyring
from node_launcher.gui.components.grid_layout import QGridLayout
from node_launcher.gui.components.horizontal_line import HorizontalLine
from node_launcher.gui.components.section_name import SectionName
from node_launcher.gui.components.seed_dialog import SeedDialog
from node_launcher.gui.components.thread_worker import Worker
from node_launcher.logging import log
from node_launcher.node_set import NodeSet
from node_launcher.node_set.lnd import Lnd
from node_launcher.node_set.lnd_client import LndClient


class LndWalletLayout(QGridLayout):
    node_set: NodeSet

    def __init__(self, node_set: NodeSet):
        super(LndWalletLayout, self).__init__()
        self.node_set = node_set
        self.password_dialog = QInputDialog()
        self.error_message = QErrorMessage()

        self.state = None

        self.threadpool = QThreadPool()

        columns = 2
        self.addWidget(SectionName('LND Wallet'), column_span=columns)
        wallet_buttons_layout = QtWidgets.QHBoxLayout()
        # Unlock wallet button
        self.unlock_wallet_button = QtWidgets.QPushButton('Unlock')
        # noinspection PyUnresolvedReferences
        self.unlock_wallet_button.clicked.connect(self.unlock_wallet)
        wallet_buttons_layout.addWidget(self.unlock_wallet_button)

        # Create wallet button
        self.create_wallet_button = QtWidgets.QPushButton('Create')
        # noinspection PyUnresolvedReferences
        self.create_wallet_button.clicked.connect(self.create_wallet)
        wallet_buttons_layout.addWidget(self.create_wallet_button,
                                        same_row=True, column=2)

        # Recover wallet button
        self.recover_wallet_button = QtWidgets.QPushButton('Recover')
        # noinspection PyUnresolvedReferences
        self.recover_wallet_button.clicked.connect(self.recover_wallet)
        wallet_buttons_layout.addWidget(self.recover_wallet_button)
        self.addLayout(wallet_buttons_layout, column_span=columns)

        self.addWidget(HorizontalLine(), column_span=columns)

    def set_button_state(self):
        old_state = self.state
        if self.node_set.lnd.running and not self.node_set.lnd.is_unlocked:
            if self.node_set.lnd.has_wallet:
                if self.state != 'unlock':
                    self.set_unlock_state()
                    self.auto_unlock_wallet()
                else:
                    return
            else:
                if self.state != 'create':
                    self.set_create_recover_state()
                else:
                    return
        elif self.node_set.lnd.running and self.node_set.lnd.is_unlocked:
            if self.state != 'open':
                self.set_open_state()
            else:
                return
        elif not self.node_set.lnd.running:
            self.node_set.lnd.is_unlocked = False
            if self.state != 'closed':
                self.set_closed_state()
            else:
                return

        log.info(
            'set_button_state',
            lnd_is_running=self.node_set.lnd.running,
            lnd_is_unlocked=self.node_set.lnd.is_unlocked,
            lnd_has_wallet=self.node_set.lnd.has_wallet,
            old_state=old_state,
            new_state=self.state
        )

    def auto_unlock_wallet(self):
        keyring_service_name = f'lnd_{self.node_set.bitcoin.network}_wallet_password'
        keyring_user_name = self.node_set.bitcoin.file['rpcuser']
        log.info(
            'auto_unlock_wallet_get_password',
            keyring_service_name=keyring_service_name,
            keyring_user_name=keyring_user_name
        )
        password = keyring.get_password(
            service=keyring_service_name,
            username=keyring_user_name,
        )
        if password is not None:
            worker = Worker(
                fn=self.lnd_poll,
                lnd=self.node_set.lnd,
                password=password
            )
            worker.signals.result.connect(self.handle_lnd_poll)
            self.threadpool.start(worker)

    @staticmethod
    def lnd_poll(lnd: Lnd, progress_callback, password: str):
        client = LndClient(lnd)
        try:
            client.unlock(password)
        except _Rendezvous as e:
            details = e.details()
            log.warning(
                'lnd_poll',
                details=details,
                exc_info=True
            )
            return details

    def handle_lnd_poll(self, details: str):
        if details is None:
            return
        details = details.lower()

        # The Wallet Unlocker gRPC service disappears from LND's API
        # after the wallet is unlocked (or created/recovered)
        if 'unknown service lnrpc.walletunlocker' in details:
            self.set_open_state()

        # User needs to create a new wallet
        elif 'wallet not found' in details:
            self.set_create_recover_state()

        # Todo: add logging for debugging
        elif 'connect failed' in details:
            pass
        else:
            self.error_message.showMessage(details)
            self.set_open_state()

    def set_unlock_state(self):
        self.state = 'unlock'
        self.create_wallet_button.setDisabled(True)
        self.recover_wallet_button.setDisabled(True)
        self.unlock_wallet_button.setDisabled(False)

    def set_create_recover_state(self):
        self.state = 'create'
        self.create_wallet_button.setDisabled(False)
        self.recover_wallet_button.setDisabled(False)
        self.unlock_wallet_button.setDisabled(True)

    def set_open_state(self):
        self.state = 'open'
        self.create_wallet_button.setDisabled(True)
        self.recover_wallet_button.setDisabled(True)
        self.unlock_wallet_button.setDisabled(True)

    def set_closed_state(self):
        self.state = 'closed'
        self.create_wallet_button.setDisabled(True)
        self.recover_wallet_button.setDisabled(True)
        self.unlock_wallet_button.setDisabled(True)

    def password_prompt(self, title: str, label: str):
        password, ok = QInputDialog.getText(
            self.password_dialog,
            title,
            label,
            QLineEdit.Password
        )
        if not ok:
            raise Exception()
        return password

    def unlock_wallet(self):
        password = self.password_prompt(
            title=f'Unlock {self.node_set.bitcoin.network} LND Wallet',
            label='Wallet Password'
        )

        try:
            self.node_set.lnd_client.unlock(wallet_password=password)
        except _Rendezvous as e:
            log.error(
                'unlock_wallet',
                exc_info=True
            )
            # noinspection PyProtectedMember
            self.error_message.showMessage(e._state.details)
            return

        timestamp = str(time.time())
        keyring_service_name = f'lnd_{self.node_set.bitcoin.network}_wallet_password'
        log.info(
            'unlock_wallet',
            keyring_service_name=keyring_service_name,
            keyring_user_name=timestamp
        )

        keyring.set_password(
            service=keyring_service_name,
            username=timestamp,
            password=password)

        keyring.set_password(
            service=keyring_service_name,
            username=self.node_set.bitcoin.file['rpcuser'],
            password=password)

    def get_new_password(self, title: str, password_name: str) -> str:
        new_password = self.password_prompt(
            title=title,
            label=f'New {password_name} Password'
        )
        confirm_password = self.password_prompt(
            title=title,
            label=f'Confirm {password_name} Password',
        )

        if new_password != confirm_password:
            self.error_message.showMessage('Passwords do not match, '
                                           'please try again!')
            return self.get_new_password(title, password_name)

        if not new_password:
            new_password = None

        return new_password

    def generate_seed(self, new_seed_password: str):
        try:
            generate_seed_response = self.node_set.lnd_client.generate_seed(
                seed_password=new_seed_password
            )
        except _Rendezvous as e:
            log.error(
                'generate_seed',
                exc_info=True
            )
            # noinspection PyProtectedMember
            self.error_message.showMessage(e._state.details)
            return

        seed = generate_seed_response.cipher_seed_mnemonic

        keyring_service_name = f'lnd_{self.node_set.bitcoin.network}_seed'
        keyring_user_name = ''.join(seed[0:2])
        log.info(
            'generate_seed',
            keyring_service_name=keyring_service_name,
            keyring_user_name=keyring_user_name
        )

        keyring.set_password(
            service=keyring_service_name,
            username=keyring_user_name,
            password=' '.join(seed)
        )

        if new_seed_password is not None:
            keyring.set_password(
                service=f'{keyring_service_name}_password',
                username=keyring_user_name,
                password=new_seed_password
            )
        return seed

    def backup_seed(self, seed):
        seed_words = [f'{index + 1}: {value}\n'
                      for index, value in enumerate(seed)]
        seed_text = ''.join(seed_words)
        seed_dialog = SeedDialog(self.parentWidget())
        seed_dialog.set_text(seed_text)
        seed_dialog.show()

    def create_wallet(self):
        new_wallet_password = self.get_new_password(
            title=f'Create {self.node_set.bitcoin.network} LND Wallet',
            password_name='LND Wallet'
        )

        keyring_service_name = f'lnd_{self.node_set.bitcoin.network}_wallet_password'
        keyring_user_name = str(time.time())
        log.info(
            'create_wallet',
            keyring_service_name=keyring_service_name,
            keyring_user_name=keyring_user_name
        )

        keyring.set_password(
            service=keyring_service_name,
            username=keyring_user_name,
            password=new_wallet_password
        )

        new_seed_password = self.get_new_password(
            title=f'Create {self.node_set.bitcoin.network} LND Wallet',
            password_name='Mnemonic Seed'
        )

        seed = self.generate_seed(new_seed_password)
        self.backup_seed(seed)

        try:
            self.node_set.lnd_client.initialize_wallet(
                wallet_password=new_wallet_password,
                seed=seed,
                seed_password=new_seed_password
            )
        except _Rendezvous as e:
            log.error(
                'initialize_wallet',
                exc_info=True
            )
            # noinspection PyProtectedMember
            self.error_message.showMessage(e._state.details)
            return

        keyring.set_password(
            service=f'lnd_{self.node_set.bitcoin.network}_wallet_password',
            username=self.node_set.bitcoin.file['rpcuser'],
            password=new_wallet_password
        )

    def recover_wallet(self):
        title = f'Recover {self.node_set.bitcoin.network} LND Wallet'
        new_wallet_password = self.get_new_password(
            title=title,
            password_name='LND Wallet'
        )

        seed_password = self.password_prompt(
            title=title,
            label='Seed Password (Optional)'
        )

        seed, ok = QInputDialog.getText(
            self.password_dialog,
            title,
            'Mnemonic Seed (one line with spaces)'
        )
        if not ok:
            raise Exception()
        seed_list = seed.split(' ')

        keyring_service_name = f'lnd_{self.node_set.bitcoin.network}'
        keyring_user_name = str(time.time())
        log.info(
            'recover_wallet',
            keyring_service_name=keyring_service_name,
            keyring_user_name=keyring_user_name
        )

        keyring.set_password(
            service=f'{keyring_service_name}_wallet_password',
            username=keyring_user_name,
            password=new_wallet_password
        )
        keyring.set_password(
            service=f'{keyring_service_name}_seed',
            username=keyring_user_name,
            password=seed
        )
        if seed_password is not None:
            keyring.set_password(
                service=f'{keyring_service_name}_seed_password',
                username=keyring_user_name,
                password=seed_password
            )

        try:
            self.node_set.lnd_client.initialize_wallet(
                wallet_password=new_wallet_password,
                seed=seed_list,
                seed_password=seed_password,
                recovery_window=10000
            )
        except _Rendezvous as e:
            log.error(
                'recover_wallet_initialize_wallet',
                exc_info=True
            )
            # noinspection PyProtectedMember
            self.error_message.showMessage(e._state.details)
            return

        keyring.set_password(
            service=f'lnd_{self.node_set.bitcoin.network}_wallet_password',
            username=self.node_set.bitcoin.file['rpcuser'],
            password=new_wallet_password
        )
