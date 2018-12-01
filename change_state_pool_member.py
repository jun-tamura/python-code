#!/usr/bin/python
# -*- coding:utf-8 -*-
#
# @Filename :change_state_pool_member.py
# @Created  :2018/12/1
#
# @�X�N���v�g�T�v
# LB�؂藣���A�؂�߂����ȈՎ��s����X�N���v�g�ł�
# "--lb_name"�Ɏw�肵��LB(a10)�ɑ΂���SSH�ڑ����s���A
# "--target"�Ɏw�肵���T�[�o�ɑΉ�����v�[�������o�[��
# "--action"�Ŏw�肵������(enable/disable)���s���܂�
#
# usage :python changeover_lb_memver.py
#        [-h]
#        --lb_name {lb_name01,lb_name02}
#        --target TARGET
#        --action {enable,disable}
#
# optional arguments:
#  -h, --help  show this help message and exit
#  --lb_name   {lb_name01,lb_name02}
#  --target    {web01,web02,proxy01,proxy02}
#  --action    {enable,disable}

import argparse
import datetime
import time
import paramiko
import sys
import re
import os
from getpass import getpass

###############
# setting from
###############

# �X�N���v�g�z�u�f�B���N�g���p�X�ݒ�
home_dir = os.path.dirname(os.path.abspath(__file__))

# ���O�o�̓f�B���N�g���ݒ�
log_dir = os.path.join(home_dir, 'log')
output_dir = os.path.join(home_dir, 'output')


# LB�ڑ����ݒ�
lb_ips = {
    "lb_name01": "10.1.1.1",
    "lb_name02": "10.1.1.2"
    }

# LB�ڑ����[�U�ݒ�
lb_admin_name = "admin"

lb_vips = {
    "web": "10.1.2.1",
    "proxy": "10.1.2.2",
    }

# �T�[�r�X�O���[�v�ҏW���[�h�ڍs�R�}���h
ent_sg = 'slb service-group {} tcp'

# �����o�[��ԕύX(enable/disable)�R�}���h
change = 'member {} {}'

# ��Ԋm�F�R�}���h
s_vrrp_a = 'show vrrp-a'
s_log_len = 'show log length {}'
s_slb_vs = 'show slb virtual-server {} | include Virtual'
s_slb_sg = 'show slb service-group {} | include State'
s_slb_srv = 'show slb server bindings | include {}'
s_run = 'show running-config'
s_run_sec = 'show running-config | section slb service-group {} tcp'

###############
# settings end
###############


def _connect(ipaddr, lb_admin_name, login_pass):
    # paramiko SSH�N���C�A���g�֐��ݒ�
    con = paramiko.SSHClient()

    # �V�X�e���t�@�C������z�X�g�������[�h
    con.load_system_host_keys()

    # known_hosts�t�@�C���ɑ��݂��Ȃ��z�X�g�ւ̐ڑ�����
    con.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    con.connect(ipaddr,
                port=22,
                username=lb_admin_name,
                password=login_pass,
                look_for_keys=False,
                allow_agent=False)

    # �Θb�^�V�F���Z�b�V�������N�G�X�g
    ssh_con = con.invoke_shell()

    time.sleep(2)

    result = ssh_con.recv(65535)

    return con, ssh_con, result


def _send_command(command, ssh_con, stdout=True, sleep=1):
    ssh_con.send(command + '\n')
    time.sleep(sleep)

    if ssh_con.recv_ready():
        result = ssh_con.recv(65535)
        if stdout is True:
            print(result + '\n')
    else:
        message = 'Send Command Error...'
        raise Exception(message)
    return result


def _enable(ssh_con, login_pass):
    result = _send_command('enable', ssh_con, stdout=False)

    result += _send_command(login_pass, ssh_con, stdout=False)

    return result


def _configure_terminal(ssh_con):
    result = _send_command('configure terminal', ssh_con, stdout=False)

    return result


def _edit_service_group(ssh_con, grp):
    result = _send_command(ent_sg.format(grp), ssh_con, stdout=False)

    return result


def _change_lb_state(ssh_con, member, act):
    result = _send_command(change.format(member, act), ssh_con, stdout=False)

    return result


def _write_memory(ssh_con):
    print('### �ݒ�ۑ� ###')
    result = _send_command('write memory', ssh_con, stdout=False)

    flg1 = False
    flg2 = False
    flg3 = False

    for line in result.splitlines():
        if "Building configuration" in line:
            flg1 = True
        elif "Write configuration" in line and hostname in line:
            flg2 = True
        elif "[OK]" in line:
            flg3 = True

    if flg1 is True and \
       flg2 is True and \
       flg3 is True:
        print('# ����ɐݒ��ۑ����܂���\n')
    else:
        message = 'Save Configuration Error...'
        raise Exception(message)

    return result


def _exit(ssh_con):
    result = _send_command('exit', ssh_con, stdout=False)

    return result


def _output_file(hostname, target, filename, text):
    date = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    path = [hostname, target, filename, date + '.log']
    filename = '_'.join(path)
    with open(os.path.join(output_dir, filename), 'w') as file:
        file.write(str(text))

    # print('\n���s���ʂ� [ ' + path + ' ] �ɕۑ����܂���\n')


def _check_redundancy(ssh_con):
    print('### �璷����Ԋm�F ###')
    result = _send_command(s_vrrp_a, ssh_con, stdout=False)

    local_state = ''
    peer_state = ''

    # �R�}���h���ʂ���Local��Peer�̏�Ԃ��`�F�b�N
    for line in result.splitlines():
        if "Local" in line:
            line = re.sub(r"\s+", " ", line)
            local_state = line.split(' ')[2]
            print("Local: " + local_state)
        elif "Peer" in line:
            line = re.sub(r"\s+", " ", line)
            peer_state = line.split(' ')[2]
            print("Peer: " + peer_state)

    # �`�F�b�N������Ԃ����ɐ��۔���
    if (local_state == "Active" and peer_state == "Standby") or \
       (local_state == "Standby" and peer_state == "Active"):
        print('�璷�\�����������\������Ă��܂�')
    else:
        print('�璷�\���ƂȂ��Ă��邱�Ƃ��m�F�ł��܂���')
        if not _is_continue():
            message = 'Processing was Canceled...'
            raise Exception(message)

    return result


def _check_log(ssh_con):
    # �ُ탍�O�L���m�F (show log length 50)
    print('### �ُ탍�O�L���m�F ###')
    result = _send_command(s_log_len.format('50'), ssh_con, stdout=False)

    # ���۔���p�ϐ���`
    error_flg = False

    # show log�̌��ʂ�1�s���`�F�b�N
    for line in result.splitlines():
        if "show log length" in line:
            continue
        elif "Log Buffer: " in line:
            continue
        elif line.startswith('ac') is True:
            continue
        elif line.split(' ')[4] == "Notice" or line.split(' ')[4] == "Info":
            continue
        else:
            # Notice�AInfo�ȊO�̃��O����������W���o�͂��ăt���O��True�ɂ���
            print(line)
            error_flg = True

    # ���O�`�F�b�N���ʔ���
    if error_flg is False:
        print('Notice�AInfo�ȊO�̃��O�͂���܂���\n')
    elif error_flg is True:
        print('���O���m�F���Ă�������\n')

    return result


def _show_slb_vs(ssh_con, hostname, target, grp):
    print('### show slb virtual-server ###')
    result = _send_command(s_slb_vs.format(grp), ssh_con, stdout=False)

    # ���s���ʂ��t�@�C���o��
    _output_file(hostname, target, "show_slb_virtual_server", result)

    return result


def _show_slb_sg(ssh_con, hostname, target, grp):
    print('### show slb service-group ###')
    result = _send_command(s_slb_sg.format(grp), ssh_con, stdout=False)

    # ���s���ʂ��t�@�C���o��
    _output_file(hostname, target, "show_slb_service_group", result)

    return result


def _show_slb_srv(ssh_con, hostname, target, grp):
    print('### show slb server ###')
    result = _send_command(s_slb_srv.format(grp), ssh_con, stdout=False)

    # ���s���ʂ��t�@�C���o��
    _output_file(hostname, target, "show_slb_server", result)

    return result


def _get_running_config(ssh_con, hostname, target):
    print('### running config�擾 ###')
    result = _send_command(s_run, ssh_con, stdout=False, sleep=5)

    # ���s���ʂ��t�@�C���o��
    _output_file(hostname, target, "show_running_config", result)
    print('running-config�����O�t�@�C���ɏo�͂��܂���\n')

    return result


def _check_state(ssh_con, grp):
    print('### �����o�[��Ԋm�F ###')
    result = _send_command(s_run_sec.format(grp), ssh_con, stdout=False)

    return result


def _is_continue():
    while True:
        choice = raw_input("\n�y�������p�����܂����H�z   [y/n] ").lower()
        if choice in ['y', 'yes']:
            return True
        elif choice in ['n', 'no']:
            return False


def run(ipaddr, hostname, lb_admin_name, login_pass, grp, act):
    member = args.target + ":80"
    vm = args.target
    vip = lb_vips[grp]
    message = ("########################################\n"
               "���s�Ώۂ����������Ƃ��m�F���Ă�������\n"
               "�Ώ�LB:   " + hostname + "\n"
               "�Ώ�VM:   " + vm + "\n"
               "�O���[�v: " + grp + "\n"
               "�����o�[: " + member + "\n"
               "�������@: " + act + "\n"
               "########################################")

    print(message + "\n")

    result = message

    try:
        # �����p���m�F
        if not _is_continue():
            message = 'Processing was Canceled...'
            raise Exception(message)

        # �Ώۃz�X�g�֐ڑ�
        con, ssh_con, tmp_result = _connect(ipaddr, lb_admin_name, login_pass)

        if hostname in tmp_result:
            message = '\n' + hostname + ' �ɐڑ����܂���\n'
            print(message)
            result += message
        else:
            message = 'LOGIN Error: ' + hostname
            raise Exception(message)

        # enable���[�h�ֈڍs
        result += _enable(ssh_con, login_pass)

        # �o�͌��ʑS�\����
        result += _send_command('terminal length 0', ssh_con, stdout=False)

        ######################
        ### �璷����Ԋm�F ###
        ######################
        result += _check_redundancy(ssh_con)

        ################
        ### ���O�m�F ###
        ################

        result += _check_log(ssh_con)

        ########################
        ### �����o�[��Ԋm�F ###
        ########################

        tmp_res = _check_state(ssh_con, grp)
        result += tmp_res

        members = {}

        # �����o�[��Ԋm�F���ʂ�1�s������
        for line in tmp_res.splitlines():
            # ����������Ă��郁���o�[�������Ɋi�[
            if "member" in line and "disable" in line:
                members[line.strip().split(' ')[1]] = "disable"
            # �L��������Ă��郁���o�[�������Ɋi�[
            elif "member" in line and "disable" not in line:
                members[line.strip().split(' ')[1]] = "enable"
        # ����[--action]�Ɏw�肵���l�ƃ����o�[�̏�Ԃ���v����ꍇ
        if act == members[member]:
            print('�Ώۂ̃����o�[�͊��� ' + act + ' �ł�\n')
            for key in members:
                value = members[key]
                print(key + ': ' + value)
            message = 'Processing was Canceled...'
            raise Exception(message)
        # ����[--action]�Ɏw�肵���l�ƃ����o�[�̏�Ԃ���v���Ȃ��ꍇ
        elif act != members[member]:
            print('�e�����o�[�̏�Ԃ͈ȉ��̒ʂ�ł�\n')
            for key in members:
                value = members[key]
                print(key + ': ' + value)
            print('\n')

        # �����o�[�̏�Ԃ��X�e�[�^�X�Ƃ��ĕϐ��ɒ�`

        # �ꕔ�����o�[������������Ă���ꍇ
        if "disable" in members.values() and \
           "enable" in members.values():
            mbr_state = "partial"
        # �S�����o�[������������Ă���ꍇ
        elif "disable" in members.values() and \
             "enable" not in members.values():
            mbr_state = "disable"
        # �S�����o�[���L��������Ă���ꍇ
        elif "disable" not in members.values() and \
             "enable" in members.values():
            mbr_state = "enable"

        ###################################
        ### show slb virtual-server�̎� ###
        ###################################

        tmp_res = _show_slb_vs(ssh_con, hostname, vm, grp)
        result += tmp_res

        # �o�͌��ʔ�r�p�^�[���̒�`
        ptn1 = grp + " State: All Up IP: " + lb_vips[grp]
        ptn2 = grp + " State: Functional Up IP: " + lb_vips[grp]

        # show slb virtual-server���s���ʂ̔��菈��
        for line in tmp_res.splitlines():
            line = re.sub(r"\s+", " ", line.strip())
            # Virtual server:�Ŏn�܂�s�̔���
            if "Virtual server:" in line:
                # �S�����o�[��enable�̏ꍇ�o�͂�ptn1�ƈ�v�����OK
                if (mbr_state == "enable") and \
                        line.lstrip("Virtual server: ") == ptn1:
                    print("Virtual server OK")
                # 1�ł�disable�̃����o�[������ꍇ�o�͂�ptn2�ƈ�v�����OK
                elif (mbr_state == "disable" or mbr_state == "partial") and \
                        line.lstrip("Virtual server: ") == ptn2:
                    print("Virtual server OK")
                # ��v���Ȃ��ꍇ��NG
                else:
                    print("Virtual server NG")
                    print(line.lstrip("Virtual server: "))
            # Virtual Port�Ŏn�܂�s�̔���
            elif "Virtual Port" in line:
                # �S�����o�[��enable�̏ꍇ�o�͂�"All Up"�������OK
                if (mbr_state == "enable") and \
                        "All Up" in line:
                    print("Virtual Port OK\n")
                # 1�ł�disable�̏ꍇ�o�͂�"Functional"�������OK
                elif (mbr_state == "disable" or mbr_state == "partial") and \
                        "Functional" in line:
                    print("Virtual Port OK\n")
                # ��L�p�^�[���Ɉ�v���Ȃ��ꍇ��NG
                else:
                    print("Virtual Port NG\n")
                    print(line + '\n')

        ##################################
        ### show slb service-group�̎� ###
        ##################################
        tmp_res = _show_slb_sg(ssh_con, hostname, vm, grp)
        result += tmp_res

        for line in tmp_res.splitlines():
            if "Service group name:" in line:
                if (mbr_state == "enable") and "All Up" in line:
                    print("Service Group State OK\n")
                elif (mbr_state == "partial") and "Functional" in line:
                    print("Service Group State OK\n")
                elif (mbr_state == "disable") and "Disb" in line:
                    print("Service Group State OK\n")
                else:
                    print("Service Group State NG\n")
                    print(line)

        ###########################
        ### show slb server�̎� ###
        ###########################
        tmp_res = _show_slb_srv(ssh_con, hostname, vm, grp)
        result += tmp_res

        for line in tmp_res.splitlines():
            line = re.sub(r"\s+", " ", line.strip())
            if line.startswith(grp) is True and ":80/tcp" in line:
                print("[ " + line.split(':')[0] + " ]")
                if line.split(' ')[-1] == "Up":
                    print(line.split(" ")[0] + " check OK")
                else:
                    print(line.split(" ")[0] + " check NG")
                    print(line + "\n")
            elif line.startswith('+' + grp) is True:
                if (mbr_state == "enable") and "All Up" in line:
                    print(line.split(" ")[0] + " check OK")
                elif (mbr_state == "partial") and "Functional" in line:
                    print(line.split(" ")[0] + " check OK")
                elif (mbr_state == "disable") and "Disb" in line:
                    print(line.split(" ")[0] + " check OK")
                else:
                    print(line.split(" ")[0] + " check NG")
                    print(line + "\n")
            elif line.startswith('+=>' + grp) is True:
                if lb_vips[grp] in line:
                    print(line.split(" ")[0] + " check OK\n")
                else:
                    print(line.split(" ")[0] + " check NG")
                    print(line + "\n")

        ###############################
        ### show running-config�擾 ###
        ###############################
        result += _get_running_config(ssh_con, hostname, vm)

        ##################################################
        ### �w�肵���T�[�r�X�O���[�v�����o�[�̐؂�ւ� ###
        ##################################################
        # config���[�h�ֈڍs
        result += _configure_terminal(ssh_con)

        # slb service-group�̕ҏW���[�h�ֈڍs
        result += _edit_service_group(ssh_con, grp)

        # �����p���m�F
        print('### �����o�[ [' + member + '] �� ' + act + '�ɕύX ###')
        if not _is_continue():
            message = 'Processing was Canceled...'
            raise Exception(message)

        # disable/enable�ݒ�؂�ւ����s
        result += _change_lb_state(ssh_con, member, act)

        # slb service-group�̕ҏW���[�h���甲����
        result += _exit(ssh_con)

        # config���[�h���甲����
        result += _exit(ssh_con)

        ########################
        ### �����o�[��Ԋm�F ###
        ########################
        tmp_res = _check_state(ssh_con, grp)
        result += tmp_res

        members = {}

        # �����o�[��Ԋm�F���ʂ�1�s������
        for line in tmp_res.splitlines():
            # ����������Ă��郁���o�[�������Ɋi�[
            if "member" in line and "disable" in line:
                members[line.strip().split(' ')[1]] = "disable"
            # �L��������Ă��郁���o�[�������Ɋi�[
            elif "member" in line and "disable" not in line:
                members[line.strip().split(' ')[1]] = "enable"
        # ����[--action]�Ɏw�肵���l�ƃ����o�[�̏�Ԃ���v����ꍇ
        if act == members[member]:
            print('�w�胁���o�[�� ' + act + ' �ɕύX����܂���\n')
            for key in members:
                value = members[key]
                print(key + ': ' + value)
            print('\n')
        # ����[--action]�Ɏw�肵���l�ƃ����o�[�̏�Ԃ���v���Ȃ��ꍇ
        elif act != members[member]:
            print('�w�胁���o�[�� ' + act + ' �ɕύX����܂���ł���\n')
            print('�e�����o�[�̏�Ԃ͈ȉ��̒ʂ�ł�\n')
            for key in members:
                value = members[key]
                print(key + ': ' + value)
            print('\n')

        # �����o�[�̏�Ԃ��X�e�[�^�X�Ƃ��ĕϐ��ɒ�`

        # �ꕔ�����o�[������������Ă���ꍇ
        if "disable" in members.values() and \
                "enable" in members.values():
            mbr_state = "partial"
        # �S�����o�[������������Ă���ꍇ
        elif "disable" in members.values() and \
                "enable" not in members.values():
            mbr_state = "disable"
        # �S�����o�[���L��������Ă���ꍇ
        elif "disable" not in members.values() and \
                "enable" in members.values():
            mbr_state = "enable"

        ################
        ### ���O�m�F ###
        ################
        result += _check_log(ssh_con)

        ###################################
        ### show slb virtual-server�̎� ###
        ###################################
        tmp_res = _show_slb_vs(ssh_con, hostname, vm, grp)
        result += tmp_res

        # show slb virtual-server���s���ʂ̔��菈��
        for line in tmp_res.splitlines():
            line = re.sub(r"\s+", " ", line.strip())
            # Virtual server:�Ŏn�܂�s�̔���
            if "Virtual server:" in line:
                # �S�����o�[��enable�̏ꍇ�o�͂�ptn1�ƈ�v�����OK
                if (mbr_state == "enable") and \
                        line.lstrip("Virtual server: ") == ptn1:
                    print("Virtual server OK")
                # 1�ł�disable�̃����o�[������ꍇ�o�͂�ptn2�ƈ�v�����OK
                elif (mbr_state == "disable" or mbr_state == "partial") and \
                        line.lstrip("Virtual server: ") == ptn2:
                    print("Virtual server OK")
                # ��v���Ȃ��ꍇ��NG
                else:
                    print("Virtual server NG")
                    print(line.lstrip("Virtual server: "))
            # Virtual Port�Ŏn�܂�s�̔���
            elif "Virtual Port" in line:
                # �S�����o�[��enable�̏ꍇ�o�͂�"All Up"�������OK
                if (mbr_state == "enable") and \
                        "All Up" in line:
                    print("Virtual Port OK\n")
                # 1�ł�disable�̏ꍇ�o�͂�"Functional"�������OK
                elif (mbr_state == "disable" or mbr_state == "partial") and \
                        "Functional" in line:
                    print("Virtual Port OK\n")
                # ��L�p�^�[���Ɉ�v���Ȃ��ꍇ��NG
                else:
                    print("Virtual Port NG\n")
                    print(line + '\n')

        ##################################
        ### show slb service-group�̎� ###
        ##################################
        tmp_res = _show_slb_sg(ssh_con, hostname, vm, grp)
        result += tmp_res

        for line in tmp_res.splitlines():
            if "Service group name:" in line:
                if (mbr_state == "enable") and "All Up" in line:
                    print("Service Group State OK\n")
                elif (mbr_state == "partial") and "Functional" in line:
                    print("Service Group State OK\n")
                elif (mbr_state == "disable") and "Disb" in line:
                    print("Service Group State OK\n")
                else:
                    print("Service Group State NG\n")
                    print(line)

        ###########################
        ### show slb server�̎� ###
        ###########################
        tmp_res = _show_slb_srv(ssh_con, hostname, vm, grp)
        result += tmp_res

        for line in tmp_res.splitlines():
            line = re.sub(r"\s+", " ", line.strip())
            if line.startswith(grp) is True and ":80/tcp" in line:
                print("[ " + line.split(':')[0] + " ]")
                if line.split(' ')[-1] == "Up":
                    print(line.split(" ")[0] + " check OK")
                else:
                    print(line.split(" ")[0] + " check NG")
                    print(line + "\n")
            elif line.startswith('+' + grp) is True:
                if (mbr_state == "enable") and "All Up" in line:
                    print(line.split(" ")[0] + " check OK")
                elif (mbr_state == "partial") and "Functional" in line:
                    print(line.split(" ")[0] + " check OK")
                elif (mbr_state == "disable") and "Disb" in line:
                    print(line.split(" ")[0] + " check OK")
                else:
                    print(line.split(" ")[0] + " check NG")
                    print(line + "\n")
            elif line.startswith('+=>' + grp) is True:
                if lb_vips[grp] in line:
                    print(line.split(" ")[0] + " check OK\n")
                else:
                    print(line.split(" ")[0] + " check NG")
                    print(line + "\n")

        ###############################
        ### show running-config�擾 ###
        ###############################
        result += _get_running_config(ssh_con, hostname, vm)

        ################
        ### �ݒ�ۑ� ###
        ################

        # �ݒ�ۑ�
        result += _write_memory(ssh_con)

        # �@�킩�烍�O�A�E�g����
        result += _exit(ssh_con)

        result += _exit(ssh_con)

        result += _send_command('y', ssh_con, stdout=False)

        print('Finish: ' + hostname)
        con.close()
        return result
    except Exception as e:
        errmsg = '\n' + hostname + ' Script Message : ' + str(e.args)
        print(errmsg)
        paramiko.SSHClient().close()
        result += errmsg
        return result


if __name__ == '__main__':
    # �w���v���b�Z�[�W�̐ݒ�
    parser = argparse.ArgumentParser(description="Changeover LB Member")

    # �R�}���h���C�������̐ݒ�
    parser.add_argument("--lb_name",
                        choices=['lb_name01', 'lb_name02'],
                        required=True)

    parser.add_argument("--target",
                        choices=['web01', 'web02',
                                 'proxy01', 'proxy02'],
                        required=True)

    parser.add_argument("--action",
                        choices=['enable', 'disable'],
                        required=True)

    args = parser.parse_args()

    # �ڑ���LB�̃z�X�g����ݒ�
    hostname = args.lb_name

    # �����Ώۃ����o�[�̑�����O���[�v����ݒ�
    grp = args.target[:-2]

    # ��������ݒ�
    act = args.action

    # �����Ɏw�肵���ڑ���LB��IP����������ݒ�
    ipaddr = lb_ips[hostname]

    if not os.path.exists(log_dir):
        print("�w�肳�ꂽ�f�B���N�g�������݂��܂���\n")
        print(log_dir)
        sys.exit(1)
    elif not os.path.exists(output_dir):
        print("�w�肳�ꂽ�f�B���N�g�������݂��܂���\n")
        print(output_dir)
        sys.exit(1)

    # ���O�C���p�X���[�h�ݒ�
    login_pass = getpass('input ' + lb_admin_name + ' password: ')

    print('Start : ' + hostname)
    date = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    strings = [hostname, args.target, act, 'result', date + '.log']
    filename = '_'.join(strings)

    with open(os.path.join(log_dir, filename), 'w') as result_log:
        result = run(ipaddr, hostname, lb_admin_name, login_pass, grp, act)
        result_log.write(str(result))