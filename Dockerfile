FROM python:3

ENV DEBIAN_FRONTEND=noninteractive

RUN sed -i 's/\/\/archive./\/\/vn.archive./g' /etc/apt/sources.list
RUN apt update && apt-get install -y --no-install-recommends git gcc apache2 rsync ansible netcat-traditional nmap net-tools lshw dos2unix libapache2-mod-wsgi-py3 openssl sshpass build-essential supervisor

WORKDIR /var/www/

# RUN git clone https://github.com/hap-wi/roxy-wi.git /var/www/haproxy-wi
ADD . /var/www/haproxy-wi

RUN chown -R www-data:www-data /var/www/haproxy-wi
RUN a2enmod cgid ssl rewrite headers proxy proxy_http proxy_wstunnel proxy_fcgi proxy_connect proxy_express proxy_fdpass proxy_scgi
# RUN pip3 install --upgrade setuptools setuptools-rust wheel
RUN pip3 install -r haproxy-wi/requirements.txt
# RUN pip3 install -r haproxy-wi/config_other/requirements_deb.txt
# RUN pip3 install --upgrade pip
# RUN systemctl restart apache2

RUN pip3 install paramiko-ng 
RUN chmod +x haproxy-wi/app/*.py haproxy-wi/app/tools/*.py
RUN cp haproxy-wi/config_other/logrotate/* /etc/logrotate.d/

RUN mkdir -p /var/lib/roxy-wi/ /var/lib/roxy-wi/keys/ /var/lib/roxy-wi/configs/ /var/lib/roxy-wi/configs/hap_config/ /var/lib/roxy-wi/configs/kp_config/ /var/lib/roxy-wi/configs/nginx_config/ /var/lib/roxy-wi/configs/apache_config/ /var/log/roxy-wi/ /etc/roxy-wi/

RUN mv haproxy-wi/roxy-wi.cfg /etc/roxy-wi
RUN openssl req -newkey rsa:4096 -nodes -keyout /var/www/haproxy-wi/app/certs/haproxy-wi.key -x509 -days 10365 -out /var/www/haproxy-wi/app/certs/haproxy-wi.crt -subj "/C=US/ST=Almaty/L=Springfield/O=Roxy-WI/OU=IT/CN=*.roxy-wi.org/emailAddress=aidaho@roxy-wi.org"
RUN chown -R www-data:www-data /var/www/haproxy-wi/ /var/lib/roxy-wi/ /var/log/roxy-wi/ /etc/roxy-wi/

# RUN systemctl daemon-reload      
# RUN systemctl restart httpd
# RUN systemctl restart rsyslog

RUN /var/www/haproxy-wi/app/create_db.py
RUN chown -R www-data:www-data /var/www/haproxy-wi/

RUN cp haproxy-wi/config_other/httpd/roxy-wi.conf /etc/apache2/sites-available/roxy-wi.conf
RUN a2ensite roxy-wi.conf

COPY ./config_other/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

VOLUME [ "/var/roxy-wi/lib", "/etc/roxy-wi" ]
EXPOSE 443 8765

# CMD ["/usr/sbin/apache2ctl", "-D", "FOREGROUND"]
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
