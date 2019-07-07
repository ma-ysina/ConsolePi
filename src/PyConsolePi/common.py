import logging
import netifaces as ni
import serial.tools.list_ports
import os
import json
import socket
import subprocess
import threading
from pathlib import Path

# Common Static Global Variables
DNS_CHECK_FILES = ['/etc/resolv.conf', '/run/dnsmasq/resolv.conf']
CONFIG_FILE = '/etc/ConsolePi/ConsolePi.conf'
LOCAL_CLOUD_FILE = '/etc/ConsolePi/cloud.data'
CLOUD_LOG_FILE = '/var/log/ConsolePi/cloud.log'
USER = 'pi' # currently not used, user pi is hardcoded using another user may have unpredictable results as it hasn't been tested
HOME = str(Path.home())

class ConsolePi_Log:

    def __init__(self, log_file=CLOUD_LOG_FILE, do_print=True, debug=None):
        self.debug = debug if debug is not None else get_config('debug')
        self.log_file = log_file
        self.do_print = do_print
        self.log = self.set_log()
        self.plog = self.log_print

    def set_log(self):
        log = logging.getLogger(__name__)
        log.setLevel(logging.INFO if not self.debug else logging.DEBUG)
        handler = logging.FileHandler(self.log_file)
        handler.setLevel(logging.INFO if not self.debug else logging.DEBUG)
        formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
        handler.setFormatter(formatter)
        log.addHandler(handler)
        return log
    
    def log_print(self, msg, level='info', end='\n'):
        getattr(self.log, level)(msg)
        if self.do_print:
            msg = '{}: {}'.format(level.upper(), msg) if level != 'info' else msg
            print(msg, end=end)


class ConsolePi_data:

    def __init__(self, log_file=CLOUD_LOG_FILE, do_print=True):
        config = self.get_config_all()
        for key, value in config.items():
            if type(value) == str:
                exec('self.{} = "{}"'.format(key, value))
            elif type(value) == bool:
                exec('self.{} = {}'.format(key, value))
                # from globals
        for key, value in globals().items():
            if type(value) == str:
                exec('self.{} = "{}"'.format(key, value))
            elif type(value) == bool or type(value) == int:
                exec('self.{} = {}'.format(key, value))
            elif type(value) == list:
                x = []
                for _ in value:
                    x.append(_)
                exec('self.{} = {}'.format(key, x))
        self.do_print = do_print
        self.log_file = log_file
        cpi_log = ConsolePi_Log(log_file=log_file, do_print=do_print, debug=self.debug)
        self.log = cpi_log.log
        self.plog = cpi_log.plog
        self.hostname = socket.gethostname()
        self.adapters = self.get_local(do_print=do_print)
        self.interfaces = self.get_if_ips()
        self.local = {self.hostname: {'adapters': self.adapters, 'interfaces': self.interfaces, 'user': 'pi'}}
        self.remotes = self.get_local_cloud_file()
    
    def get_config_all(self):
        with open('/etc/ConsolePi/ConsolePi.conf', 'r') as config:
            for line in config:
                if 'ConsolePi Configuration File ver' not in line:
                    var = line.split("=")[0]
                    value = line.split('#')[0]
                    value = value.replace('{0}='.format(var), '')
                    value = value.split('#')[0]
                    if '"' in value:
                        value = value.replace('"', '', 1)
                        value = value.split('"')
                        value = value[0]
                    
                    if 'true' in value.lower() or 'false' in value.lower():
                        value = True if 'true' in value.lower() else False
                        
                    locals()[var] = value
        ret_data = locals()
        ret_data.pop('config')
        ret_data.pop('line')
        return ret_data

    def get_local(self, do_print=True):   
        log = self.log
        plog = self.plog

        plog('Detecting Locally Attached Serial Adapters')
        this = serial.tools.list_ports.grep('.*ttyUSB[0-9]*', include_links=True)
        tty_list = {}
        tty_alias_list = {}
        for x in this:
            _device_path = x.device_path.split('/')
            if x.device.replace('/dev/', '') != _device_path[len(_device_path)-1]:
                tty_alias_list[x.device_path] = x.device
            else:
                tty_list[x.device_path] = x.device

        final_tty_list = []
        for k in tty_list:
            if k in tty_alias_list:
                final_tty_list.append(tty_alias_list[k])
            else:
                final_tty_list.append(tty_list[k])

        # get telnet port definition from ser2net.conf
        # and build adapters dict
        serial_list = []
        if os.path.isfile('/etc/ser2net.conf'):
            for tty_dev in final_tty_list:
                with open('/etc/ser2net.conf', 'r') as cfg:
                    for line in cfg:
                        if tty_dev in line:
                            tty_port = line.split(':')
                            tty_port = tty_port[0]
                            log.info('get_local: found dev: {} TELNET port: {}'.format(tty_dev, tty_port))
                            break
                        else:
                            tty_port = 7000  # this is error - placeholder value Telnet port is not currently used
                serial_list.append({'dev': tty_dev, 'port': tty_port})
                if tty_port == 7000:
                    log.error('No ser2net.conf definition found for {}'.format(tty_dev))
                    print('No ser2net.conf definition found for {}'.format(tty_dev))
        else:
            log.error('No ser2net.conf file found unable to extract port definition')
            print('No ser2net.conf file found unable to extract port definition')

        return serial_list

    def get_if_ips(self):
        log=self.log
        if_list = ni.interfaces()
        log.debug('interface list: {}'.format(if_list))
        if_data = {}
        for _if in if_list:
            if _if != 'lo':
                try:
                    if_data[_if] = {'ip': ni.ifaddresses(_if)[ni.AF_INET][0]['addr'], 'mac': ni.ifaddresses(_if)[ni.AF_LINK][0]['addr']}
                except KeyError:
                    log.info('No IP Found for {} skipping'.format(_if))
        log.debug('get_if_ips complete: {}'.format(if_data))
        return if_data

    def get_local_cloud_file(self, local_cloud_file=LOCAL_CLOUD_FILE):
        data = {}
        if os.path.isfile(local_cloud_file):
            with open(local_cloud_file, mode='r') as cloud_file:
                data = json.load(cloud_file)
        return data

    def update_local_cloud_file(self, remote_consoles=None, current_remotes=None, local_cloud_file=LOCAL_CLOUD_FILE):
        # NEW gets current remotes from file and updates with new
        log = self.log
        if remote_consoles is not None and len(remote_consoles) > 0:
            if os.path.isfile(local_cloud_file):
                if current_remotes is None:
                    current_remotes = self.get_local_cloud_file()
                os.remove(local_cloud_file)

            # update current_remotes dict with data passed to function
            # TODO # can refactor to check both when there is a conflict and use api to verify consoles, but I *think* logic below should work.
            if current_remotes is not None:
                for _ in current_remotes:
                    if _ not in remote_consoles:
                        # if source == 'mdns' and source in current_remotes[_] and current_remotes[_]['source'] != 'mdns':
                        remote_consoles[_] = current_remotes[_]
                    else:
                        # only factor in existing data if source is not mdns
                        if remote_consoles[_]['source'] != 'mdns' and 'source' in current_remotes[_] and current_remotes[_]['source'] == 'mdns':
                            if 'rem_ip' in current_remotes[_] and current_remotes[_]['rem_ip'] is not None:
                                # given all of the above it would appear the mdns entry is more current than the cloud entry
                                remote_consoles[_] = current_remotes[_]
                        elif remote_consoles[_]['source'] != 'mdns':
                                if 'rem_ip' in current_remotes[_] and current_remotes[_]['rem_ip'] is not None:
                                    # if we currently have a reachable ip assume whats in the cache is more valid
                                    remote_consoles[_]['rem_ip'] = current_remotes[_]['rem_ip']

                                    if len(current_remotes[_]['adapters']) > 0 and len(remote_consoles[_]['adapters']) == 0:
                                        log.info('My Adapter data for {} is more current, keeping'.format(_))
                                        remote_consoles[_]['adapters'] = current_remotes[_]['adapters']
        
            with open(local_cloud_file, 'a') as new_file:
                new_file.write(json.dumps(remote_consoles))
        else:
            log.warning('update_local_cloud_file called with no data passed, doing nothing')
        
        return remote_consoles

# Get Variables from Config
def get_config(var):
    with open(CONFIG_FILE, 'r') as cfg:
        for line in cfg:
            if var in line:
                var_out = line.replace('{0}='.format(var), '')
                var_out = var_out.split('#')[0]
                if '"' in var_out:
                    var_out = var_out.replace('"', '', 1)
                    var_out = var_out.split('"')
                    var_out = var_out[0]
                break

    if 'true' in var_out.lower() or 'false' in var_out.lower():
        var_out = True if 'true' in var_out.lower() else False

    return var_out

def bash_command(cmd):
    subprocess.run(['/bin/bash', '-c', cmd])


def is_valid_ipv4_address(address):
    try:
        socket.inet_pton(socket.AF_INET, address)
    except AttributeError:  # no inet_pton here, sorry
        try:
            socket.inet_aton(address)
        except socket.error:
            return False
        return address.count('.') == 3
    except socket.error:  # not a valid address
        return False

    return True


def get_dns_ips(dns_check_files=DNS_CHECK_FILES):
    dns_ips = []

    for file in dns_check_files:
        with open(file) as fp:
            for cnt, line in enumerate(fp):
                columns = line.split()
                if columns[0] == 'nameserver':
                    ip = columns[1:][0]
                    if is_valid_ipv4_address(ip):
                        if ip != '127.0.0.1':
                            dns_ips.append(ip)

    return dns_ips


def check_reachable(ip, port, timeout=2):
    # if url is passed check dns first otherwise dns resolution failure causes longer delay
    if '.com' in ip:
        test_set = [get_dns_ips()[0], ip]
        timeout += 3
    else:
        test_set = [ip]

    cnt = 0
    for _ip in test_set:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            sock.connect((_ip, 53 if cnt == 0 and len(test_set) > 1 else port ))
            reachable = True
        except (socket.error, TimeoutError):
            reachable = False
        sock.close()
        cnt += 1

        if not reachable:
            break
    return reachable

def gen_copy_key(rem_ip, rem_user='pi', hostname=None, copy=False):
    if hostname is None:
        hostname = socket.gethostname()
    if not os.path.isfile(HOME + '/.ssh/id_rsa'):
        print('\n\nNo Local ssh cert found, generating...')
        bash_command('ssh-keygen -m pem -t rsa -C "{0}@{1}"'.format(rem_user, hostname))
        copy = True
    if copy:
        print('\nAttempting to copy ssh cert to {}\n'.format(rem_ip))
        bash_command('ssh-copy-id {0}@{1}'.format(rem_user, rem_ip))