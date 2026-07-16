from django.core.mail.backends.smtp import EmailBackend as DjangoEmailBackend

class Python312EmailBackend(DjangoEmailBackend):
    def open(self):
        """
        An open connection method that is compatible with Python 3.12+ by avoiding
        passing keyfile/certfile arguments to SMTP.starttls() if they are not used.
        """
        if self.connection:
            return False

        from django.core.mail.utils import DNS_NAME
        connection_params = {'local_hostname': DNS_NAME.get_fqdn()}
        if self.timeout is not None:
            connection_params['timeout'] = self.timeout

        try:
            self.connection = self.connection_class(self.host, self.port, **connection_params)

            if not self.use_ssl and self.use_tls:
                # Avoid passing deprecated/removed keyfile/certfile kwargs for starttls
                self.connection.starttls()

            if self.username and self.password:
                self.connection.login(self.username, self.password)
            return True
        except OSError:
            if not self.fail_silently:
                raise
