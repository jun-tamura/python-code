#!/usr/bin/python
# -*- coding:utf-8 -*-
#
# @Filename :change_state_pool_member.py
# @Created  :2018/12/1
#
# @スクリプト概要
# LB切り離し、切り戻しを簡易実行するスクリプトです
# "--lb_name"に指定したLB(a10)に対してSSH接続を行い、
# "--target"に指定したサーバに対応するプールメンバーに
# "--action"で指定した処理(enable/disable)を行います
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

# スクリプト配置ディレクトリパス設定
home_dir = os.path.dirname(os.path.abspath(__file__))

# ログ出力ディレクトリ設定
log_dir = os.path.join(home_dir, 'log')
output_dir = os.path.join(home_dir, 'output')


# LB接続情報設定
lb_ips = {
    "lb_name01": "10.1.1.1",
    "lb_name02": "10.1.1.2"
    }

# LB接続ユーザ設定
lb_admin_name = "admin"

lb_vips = {
    "web": "10.1.2.1",
    "proxy": "10.1.2.2",
    }

# サービスグループ編集モード移行コマンド
ent_sg = 'slb service-group {} tcp'

# メンバー状態変更(enable/disable)コマンド
change = 'member {} {}'

# 状態確認コマンド
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
    # paramiko SSHクライアント関数設定
    con = paramiko.SSHClient()

    # システムファイルからホスト鍵をロード
    con.load_system_host_keys()

    # known_hostsファイルに存在しないホストへの接続許可
    con.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    con.connect(ipaddr,
                port=22,
                username=lb_admin_name,
                password=login_pass,
                look_for_keys=False,
                allow_agent=False)

    # 対話型シェルセッションリクエスト
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
    print('### 設定保存 ###')
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
        print('# 正常に設定を保存しました\n')
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

    # print('\n実行結果を [ ' + path + ' ] に保存しました\n')


def _check_redundancy(ssh_con):
    print('### 冗長化状態確認 ###')
    result = _send_command(s_vrrp_a, ssh_con, stdout=False)

    local_state = ''
    peer_state = ''

    # コマンド結果からLocalとPeerの状態をチェック
    for line in result.splitlines():
        if "Local" in line:
            line = re.sub(r"\s+", " ", line)
            local_state = line.split(' ')[2]
            print("Local: " + local_state)
        elif "Peer" in line:
            line = re.sub(r"\s+", " ", line)
            peer_state = line.split(' ')[2]
            print("Peer: " + peer_state)

    # チェックした状態を元に正否判定
    if (local_state == "Active" and peer_state == "Standby") or \
       (local_state == "Standby" and peer_state == "Active"):
        print('冗長構成が正しく構成されています')
    else:
        print('冗長構成となっていることが確認できません')
        if not _is_continue():
            message = 'Processing was Canceled...'
            raise Exception(message)

    return result


def _check_log(ssh_con):
    # 異常ログ有無確認 (show log length 50)
    print('### 異常ログ有無確認 ###')
    result = _send_command(s_log_len.format('50'), ssh_con, stdout=False)

    # 正否判定用変数定義
    error_flg = False

    # show logの結果を1行ずつチェック
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
            # Notice、Info以外のログがあったら標準出力してフラグをTrueにする
            print(line)
            error_flg = True

    # ログチェック結果判定
    if error_flg is False:
        print('Notice、Info以外のログはありません\n')
    elif error_flg is True:
        print('ログを確認してください\n')

    return result


def _show_slb_vs(ssh_con, hostname, target, grp):
    print('### show slb virtual-server ###')
    result = _send_command(s_slb_vs.format(grp), ssh_con, stdout=False)

    # 実行結果をファイル出力
    _output_file(hostname, target, "show_slb_virtual_server", result)

    return result


def _show_slb_sg(ssh_con, hostname, target, grp):
    print('### show slb service-group ###')
    result = _send_command(s_slb_sg.format(grp), ssh_con, stdout=False)

    # 実行結果をファイル出力
    _output_file(hostname, target, "show_slb_service_group", result)

    return result


def _show_slb_srv(ssh_con, hostname, target, grp):
    print('### show slb server ###')
    result = _send_command(s_slb_srv.format(grp), ssh_con, stdout=False)

    # 実行結果をファイル出力
    _output_file(hostname, target, "show_slb_server", result)

    return result


def _get_running_config(ssh_con, hostname, target):
    print('### running config取得 ###')
    result = _send_command(s_run, ssh_con, stdout=False, sleep=5)

    # 実行結果をファイル出力
    _output_file(hostname, target, "show_running_config", result)
    print('running-configをログファイルに出力しました\n')

    return result


def _check_state(ssh_con, grp):
    print('### メンバー状態確認 ###')
    result = _send_command(s_run_sec.format(grp), ssh_con, stdout=False)

    return result


def _is_continue():
    while True:
        choice = raw_input("\n【処理を継続しますか？】   [y/n] ").lower()
        if choice in ['y', 'yes']:
            return True
        elif choice in ['n', 'no']:
            return False


def run(ipaddr, hostname, lb_admin_name, login_pass, grp, act):
    member = args.target + ":80"
    vm = args.target
    vip = lb_vips[grp]
    message = ("########################################\n"
               "実行対象が正しいことを確認してください\n"
               "対象LB:   " + hostname + "\n"
               "対象VM:   " + vm + "\n"
               "グループ: " + grp + "\n"
               "メンバー: " + member + "\n"
               "処理方法: " + act + "\n"
               "########################################")

    print(message + "\n")

    result = message

    try:
        # 処理継続確認
        if not _is_continue():
            message = 'Processing was Canceled...'
            raise Exception(message)

        # 対象ホストへ接続
        con, ssh_con, tmp_result = _connect(ipaddr, lb_admin_name, login_pass)

        if hostname in tmp_result:
            message = '\n' + hostname + ' に接続しました\n'
            print(message)
            result += message
        else:
            message = 'LOGIN Error: ' + hostname
            raise Exception(message)

        # enableモードへ移行
        result += _enable(ssh_con, login_pass)

        # 出力結果全表示化
        result += _send_command('terminal length 0', ssh_con, stdout=False)

        ######################
        ### 冗長化状態確認 ###
        ######################
        result += _check_redundancy(ssh_con)

        ################
        ### ログ確認 ###
        ################

        result += _check_log(ssh_con)

        ########################
        ### メンバー状態確認 ###
        ########################

        tmp_res = _check_state(ssh_con, grp)
        result += tmp_res

        members = {}

        # メンバー状態確認結果を1行ずつ判定
        for line in tmp_res.splitlines():
            # 無効化されているメンバーを辞書に格納
            if "member" in line and "disable" in line:
                members[line.strip().split(' ')[1]] = "disable"
            # 有効化されているメンバーを辞書に格納
            elif "member" in line and "disable" not in line:
                members[line.strip().split(' ')[1]] = "enable"
        # 引数[--action]に指定した値とメンバーの状態が一致する場合
        if act == members[member]:
            print('対象のメンバーは既に ' + act + ' です\n')
            for key in members:
                value = members[key]
                print(key + ': ' + value)
            message = 'Processing was Canceled...'
            raise Exception(message)
        # 引数[--action]に指定した値とメンバーの状態が一致しない場合
        elif act != members[member]:
            print('各メンバーの状態は以下の通りです\n')
            for key in members:
                value = members[key]
                print(key + ': ' + value)
            print('\n')

        # メンバーの状態をステータスとして変数に定義

        # 一部メンバーが無効化されている場合
        if "disable" in members.values() and \
           "enable" in members.values():
            mbr_state = "partial"
        # 全メンバーが無効化されている場合
        elif "disable" in members.values() and \
             "enable" not in members.values():
            mbr_state = "disable"
        # 全メンバーが有効化されている場合
        elif "disable" not in members.values() and \
             "enable" in members.values():
            mbr_state = "enable"

        ###################################
        ### show slb virtual-server採取 ###
        ###################################

        tmp_res = _show_slb_vs(ssh_con, hostname, vm, grp)
        result += tmp_res

        # 出力結果比較パターンの定義
        ptn1 = grp + " State: All Up IP: " + lb_vips[grp]
        ptn2 = grp + " State: Functional Up IP: " + lb_vips[grp]

        # show slb virtual-server実行結果の判定処理
        for line in tmp_res.splitlines():
            line = re.sub(r"\s+", " ", line.strip())
            # Virtual server:で始まる行の判定
            if "Virtual server:" in line:
                # 全メンバーがenableの場合出力がptn1と一致すればOK
                if (mbr_state == "enable") and \
                        line.lstrip("Virtual server: ") == ptn1:
                    print("Virtual server OK")
                # 1つでもdisableのメンバーがある場合出力がptn2と一致すればOK
                elif (mbr_state == "disable" or mbr_state == "partial") and \
                        line.lstrip("Virtual server: ") == ptn2:
                    print("Virtual server OK")
                # 一致しない場合はNG
                else:
                    print("Virtual server NG")
                    print(line.lstrip("Virtual server: "))
            # Virtual Portで始まる行の判定
            elif "Virtual Port" in line:
                # 全メンバーがenableの場合出力に"All Up"があればOK
                if (mbr_state == "enable") and \
                        "All Up" in line:
                    print("Virtual Port OK\n")
                # 1つでのdisableの場合出力に"Functional"があればOK
                elif (mbr_state == "disable" or mbr_state == "partial") and \
                        "Functional" in line:
                    print("Virtual Port OK\n")
                # 上記パターンに一致しない場合はNG
                else:
                    print("Virtual Port NG\n")
                    print(line + '\n')

        ##################################
        ### show slb service-group採取 ###
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
        ### show slb server採取 ###
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
        ### show running-config取得 ###
        ###############################
        result += _get_running_config(ssh_con, hostname, vm)

        ##################################################
        ### 指定したサービスグループメンバーの切り替え ###
        ##################################################
        # configモードへ移行
        result += _configure_terminal(ssh_con)

        # slb service-groupの編集モードへ移行
        result += _edit_service_group(ssh_con, grp)

        # 処理継続確認
        print('### メンバー [' + member + '] を ' + act + 'に変更 ###')
        if not _is_continue():
            message = 'Processing was Canceled...'
            raise Exception(message)

        # disable/enable設定切り替え実行
        result += _change_lb_state(ssh_con, member, act)

        # slb service-groupの編集モードから抜ける
        result += _exit(ssh_con)

        # configモードから抜ける
        result += _exit(ssh_con)

        ########################
        ### メンバー状態確認 ###
        ########################
        tmp_res = _check_state(ssh_con, grp)
        result += tmp_res

        members = {}

        # メンバー状態確認結果を1行ずつ判定
        for line in tmp_res.splitlines():
            # 無効化されているメンバーを辞書に格納
            if "member" in line and "disable" in line:
                members[line.strip().split(' ')[1]] = "disable"
            # 有効化されているメンバーを辞書に格納
            elif "member" in line and "disable" not in line:
                members[line.strip().split(' ')[1]] = "enable"
        # 引数[--action]に指定した値とメンバーの状態が一致する場合
        if act == members[member]:
            print('指定メンバーが ' + act + ' に変更されました\n')
            for key in members:
                value = members[key]
                print(key + ': ' + value)
            print('\n')
        # 引数[--action]に指定した値とメンバーの状態が一致しない場合
        elif act != members[member]:
            print('指定メンバーが ' + act + ' に変更されませんでした\n')
            print('各メンバーの状態は以下の通りです\n')
            for key in members:
                value = members[key]
                print(key + ': ' + value)
            print('\n')

        # メンバーの状態をステータスとして変数に定義

        # 一部メンバーが無効化されている場合
        if "disable" in members.values() and \
                "enable" in members.values():
            mbr_state = "partial"
        # 全メンバーが無効化されている場合
        elif "disable" in members.values() and \
                "enable" not in members.values():
            mbr_state = "disable"
        # 全メンバーが有効化されている場合
        elif "disable" not in members.values() and \
                "enable" in members.values():
            mbr_state = "enable"

        ################
        ### ログ確認 ###
        ################
        result += _check_log(ssh_con)

        ###################################
        ### show slb virtual-server採取 ###
        ###################################
        tmp_res = _show_slb_vs(ssh_con, hostname, vm, grp)
        result += tmp_res

        # show slb virtual-server実行結果の判定処理
        for line in tmp_res.splitlines():
            line = re.sub(r"\s+", " ", line.strip())
            # Virtual server:で始まる行の判定
            if "Virtual server:" in line:
                # 全メンバーがenableの場合出力がptn1と一致すればOK
                if (mbr_state == "enable") and \
                        line.lstrip("Virtual server: ") == ptn1:
                    print("Virtual server OK")
                # 1つでもdisableのメンバーがある場合出力がptn2と一致すればOK
                elif (mbr_state == "disable" or mbr_state == "partial") and \
                        line.lstrip("Virtual server: ") == ptn2:
                    print("Virtual server OK")
                # 一致しない場合はNG
                else:
                    print("Virtual server NG")
                    print(line.lstrip("Virtual server: "))
            # Virtual Portで始まる行の判定
            elif "Virtual Port" in line:
                # 全メンバーがenableの場合出力に"All Up"があればOK
                if (mbr_state == "enable") and \
                        "All Up" in line:
                    print("Virtual Port OK\n")
                # 1つでのdisableの場合出力に"Functional"があればOK
                elif (mbr_state == "disable" or mbr_state == "partial") and \
                        "Functional" in line:
                    print("Virtual Port OK\n")
                # 上記パターンに一致しない場合はNG
                else:
                    print("Virtual Port NG\n")
                    print(line + '\n')

        ##################################
        ### show slb service-group採取 ###
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
        ### show slb server採取 ###
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
        ### show running-config取得 ###
        ###############################
        result += _get_running_config(ssh_con, hostname, vm)

        ################
        ### 設定保存 ###
        ################

        # 設定保存
        result += _write_memory(ssh_con)

        # 機器からログアウトする
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
    # ヘルプメッセージの設定
    parser = argparse.ArgumentParser(description="Changeover LB Member")

    # コマンドライン引数の設定
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

    # 接続先LBのホスト名を設定
    hostname = args.lb_name

    # 処理対象メンバーの属するグループ名を設定
    grp = args.target[:-2]

    # 処理動作設定
    act = args.action

    # 引数に指定した接続先LBのIPを辞書から設定
    ipaddr = lb_ips[hostname]

    if not os.path.exists(log_dir):
        print("指定されたディレクトリが存在しません\n")
        print(log_dir)
        sys.exit(1)
    elif not os.path.exists(output_dir):
        print("指定されたディレクトリが存在しません\n")
        print(output_dir)
        sys.exit(1)

    # ログインパスワード設定
    login_pass = getpass('input ' + lb_admin_name + ' password: ')

    print('Start : ' + hostname)
    date = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    strings = [hostname, args.target, act, 'result', date + '.log']
    filename = '_'.join(strings)

    with open(os.path.join(log_dir, filename), 'w') as result_log:
        result = run(ipaddr, hostname, lb_admin_name, login_pass, grp, act)
        result_log.write(str(result))