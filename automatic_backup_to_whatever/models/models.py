# -*- coding: utf-8 -*-

from odoo import models, fields, api, exceptions, service
from enum import Enum

import boto3
import botocore
import pysftp
import dropbox
from dropbox import exceptions as dropbox_exceptions

import owncloud

import os
import datetime


class BackupTypes(Enum):
    """
    Definition of all Backuptypes
    """

    s3 = ('s3', 'Amazon Web-Service S3')
    dropbox = ('dropbox', 'Dropbox')
    owncloud = ('owncloud', 'ownCloud/nextCloud')
    sftp = ('sftp', 'SFTP')


class Configuration(models.Model):
    """
    The Backup Configuration Model
    """

    _name = 'automatic_backup_to_whatever.configuration'
    _description = 'Backup Configuration'
    _inherit = ['mail.thread']

    name = fields.Char('Name', required=1)
    active = fields.Boolean('is Active', default=0)
    state = fields.Selection([('disabled', 'Disabled'),('active', 'Active')],
                             default='disabled', readonly=1)

    # Automatic Action
    # Assigned on activation
    cron_id = fields.Many2one('ir.cron', ondelete='cascade')

    # Same values as in automatic action
    # they will be transferred to the automatic-action after write and activation
    schedule_frequently = fields.Selection(string='Every', selection=[('days', 'Days'), ('weeks', 'Weeks')],
                                           default='weeks', required=1)
    schedule_number = fields.Integer('Schedule Number', min=1, default=1, required=1)
    next_backup_time = fields.Datetime('Next Backup Time', store=0, readonly=1, compute='_compute_next_backup_time')

    # Mail to after backup is executed
    success_mail = fields.Many2one('res.users', ondelete='set null')
    error_mail = fields.Many2one('res.users', ondelete='set null')

    # Changes view of Attributes
    backup_type = fields.Selection([
        BackupTypes.s3.value, BackupTypes.dropbox.value,
        BackupTypes.owncloud.value, BackupTypes.sftp.value
    ], required=1)

    upload_path = fields.Char("Path to upload")

    # Just loginfo
    last_backup = fields.Datetime(readonly=1)
    last_message = fields.Char(readonly=1)
    last_path = fields.Char(readonly=1)

    # Variables only needed for view visibility
    # They are not stored!
    show_s3 = fields.Boolean(compute='set_show_s3', store=0)
    show_dropbox = fields.Boolean(compute='set_show_dropbox', store=0)
    show_owncloud = fields.Boolean(compute='set_show_owncloud', store=0)
    show_sftp = fields.Boolean(compute='set_show_sftp', store=0)
    show_access_key = fields.Boolean(compute='set_show_access_key', store=0)
    show_secret_key = fields.Boolean(compute='set_show_secret_key', store=0)
    show_login_cred = fields.Boolean(compute='set_show_login_cred', store=0)

    # Required for Dropbox/S3
    access_key_id = fields.Char("Access Key")
    # Required for S3
    secret_access_key = fields.Char("Secret Key")
    s3_bucket_name = fields.Char("BucketName")

    # Required for owncloud/nextcloud/sftp
    cloud_url = fields.Char('URL')
    # Required for sftp
    cloud_port = fields.Char('Port')
    # Required for owncloud/nextcloud/sftp
    cloud_username = fields.Char('Username')
    cloud_password = fields.Char('Password')

    @api.model
    def create(self, vals):
        """
        Inherited create-method...
        ...to check and change upload-path
        """
        vals = self.check_upload_path(vals)
        result = super(Configuration, self).create(vals)
        return result

    @api.multi
    def write(self, vals):
        """
        Inherited write-method...
        ...to check and change upload-path
        ...to override attributes to automatic action
        """
        self.ensure_one()
        vals = self.check_upload_path(vals)
        result = super(Configuration, self).write(vals)
        if self.cron_id:
            if 'name' in vals:
                self.cron_id.write({'name': 'Backup: '+self.name})
            if 'active' in vals:
                self.cron_id.write({'active': self.active})
            if 'interval_number' in vals:
                self.cron_id.write({'interval_number': self.schedule_number})
            if 'interval_type' in vals:
                self.cron_id.write({'interval_type': self.schedule_frequently})
        return result

    @api.multi
    def unlink(self):
        """
            Inherited unlink-method...
            ...to remove automatic action before delete
        """

        """
        for record in self:
            if record.cron_id:
                cron_id = record.cron_id
                record.cron_id = False
                if cron_id:
                    cron_id.unlink()"""
        result = super(Configuration, self).unlink()
        return result

    def check_upload_path(self, vals):
        """

        :param vals:
        :return: vals with correct path
        """
        if 'upload_path' in vals and vals['upload_path']:
            vals['upload_path'] = vals['upload_path'].replace('\\', '/')
            vals['upload_path'] = ''.join(
                vals['upload_path'][i] for i in range(len(vals['upload_path'])-1)
                if (i != 0 and vals['upload_path'][i-1] != vals['upload_path'][i]) or vals['upload_path'][i] != '/' or (vals['upload_path'][i] == '/' and i == 0)
            )
            if len(vals['upload_path']):
                if '/' != vals['upload_path'][0]:
                    vals['upload_path'] = '/' + vals['upload_path']
                if '/' != vals['upload_path'][-1]:
                    vals['upload_path'] = vals['upload_path'] + '/'
            else:
                vals['upload_path'] = '/'
        elif 'upload_path' in vals and not vals['upload_path']:
            vals['upload_path'] = '/'
        return vals

    def set_show_s3(self):
        self.show_s3 = (self.backup_type == BackupTypes.s3.value[0])

    def set_show_dropbox(self):
        self.show_dropbox = (self.backup_type == BackupTypes.dropbox.value[0])

    def set_show_owncloud(self):
        self.show_owncloud = (self.backup_type == BackupTypes.owncloud.value[0])

    def set_show_sftp(self):
        self.show_sftp = (self.backup_type == BackupTypes.sftp.value[0])

    def set_show_access_key(self):
        self.show_access_key = (
            (self.backup_type == BackupTypes.s3.value[0])
            or (self.backup_type == BackupTypes.dropbox.value[0])
        )

    def set_show_secret_key(self):
        self.show_secret_key = (self.backup_type == BackupTypes.s3.value[0])

    def set_show_login_cred(self):
        self.show_login_cred = (
            (self.backup_type == BackupTypes.owncloud.value[0])
            or (self.backup_type == BackupTypes.sftp.value[0])
        )

    def _compute_next_backup_time(self):
        if self.cron_id:
            self.next_backup_time = self.cron_id.nextcall

    @api.onchange('backup_type')
    def onchange_backup_type(self):
        self.set_show_s3()
        self.set_show_access_key()
        self.set_show_secret_key()
        self.set_show_owncloud()
        self.set_show_dropbox()
        self.set_show_sftp()
        self.set_show_login_cred()

    def action_backup(self, id):
        backup_ids = self.search([id])
        for backup in backup_ids:
            backup.btn_action_backup()

    @api.multi
    def btn_action_backup(self):
        self.ensure_one()
        try:
            if self.backup_type == BackupTypes.s3.value[0]:
                self._backup_on_s3()
            elif self.backup_type == BackupTypes.dropbox.value[0]:
                self._backup_on_dropbox()
            elif self.backup_type == BackupTypes.owncloud.value[0]:
                self._backup_on_owncloud()
            elif self.backup_type == BackupTypes.sftp.value[0]:
                self._backup_on_sftp()
            self.send_email()
        except Exception as err:
            i = 0 if self.backup_type != BackupTypes.sftp.value[0] else 1
            self.set_last_fields(err.args[i])
            self.message_post(err.args[i])
            self.send_email(success=False)

    def send_email(self, success=True):
        if ((success and self.success_mail.id is not False) or (not success and self.error_mail.id is not False)):
            template_name = 'backup_configuration_success_template' if success else 'backup_configuration_error_template'
            template = self.env.ref('automatic_backup_to_whatever.'+template_name)
            self.env['mail.template'].browse(template.id).send_mail(self.id, force_send=True)

    def _backup_on_s3(self):
        if self.access_key_id is False or self.secret_access_key is False:
            raise exceptions.MissingError("AWS S3: You need to add a AccessKey and a SecretAccessKey!")
        if self.s3_bucket_name is False:
            raise exceptions.MissingError("AWS S3: You need to add a BucketName!")

        client = boto3.client('s3', aws_access_key_id=self.access_key_id, aws_secret_access_key=self.secret_access_key)
        path, content = self.get_path_and_content()

        try:
            client.put_object(Bucket=self.s3_bucket_name, Body=content, Key=path)
        except botocore.exceptions.ClientError as client_err:
            raise exceptions.ValidationError(
                "AWS S3: " + client_err.response['Error']['Message'])
        else:
            message = ("AWS S3: No Error during upload. You can find the backup under the bucket {0} with the "
                      "name {1}".format(self.s3_bucket_name, path))
            self.set_last_fields(message, path=path)
            self.message_post(message)

    def _backup_on_dropbox(self):
        dbx = dropbox.Dropbox(self.access_key_id)
        path, content = self.get_path_and_content()
        try:
            dbx.files_upload(content.read(), path)
        except dropbox_exceptions.AuthError:
            raise exceptions.ValidationError("Dropbox: Wrong Access Key!")
        else:
            message = ("Dropbox: No Error during upload. You can find the backup under the name {0}".format(path))
            self.set_last_fields(message, path=path)
            self.message_post(message)

    def _backup_on_owncloud(self):
        oc = owncloud.Client(self.cloud_url)
        try:
            oc.login(self.cloud_username, self.cloud_password)
        except Exception as err:
            raise exceptions.ValidationError("ownCloud: Check your Creds!")
        path, content = self.get_path_and_content()
        try:
            oc.put_file_contents(path, content.read())
        except Exception as err:
            if err.status_code == 404:
                raise exceptions.ValidationError("Folder not found!")
            raise err
        message = ("ownCloud: No Error during upload. You can find the backup under {0}".format(path))
        self.set_last_fields(message, path=path)
        self.message_post(message)

    def _backup_on_sftp(self):
        try:
            port = int(self.cloud_port)
        except:
            raise exceptions.ValidationError("Port has to be between 1 and 65535")
        else:
            with pysftp.Connection(host=self.cloud_url,
                                    username=self.cloud_username,
                                    password=self.cloud_password,
                                    port=port) as sftp:
                path, content = self.get_path_and_content()
                sftp.putfo(content, remotepath=path)
            message = ("sftp: No Error during upload. You can find the backup under {0}".format(path))
            self.set_last_fields(message, path=path)
            self.message_post(message)

    def get_path_and_content(self):
        filename, content = self.get_backup()
        path = os.path.join(self.upload_path, filename)
        return path, content

    def get_backup(self, dbname=None, backup_format='zip'):
        if dbname is None:
            dbname = self._cr.dbname
        ts = datetime.datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")
        filename = "%s_%s.%s" % (dbname, ts, backup_format)
        dump_stream = service.db.dump_db(dbname, None, backup_format)
        return filename, dump_stream

    def set_last_fields(self, message, path=None):
        if path is not None:
            self.last_path = path
            self.last_backup = datetime.datetime.now()
        self.last_message = message

    def deactivate_progressbar(self):
        self.active = False
        self.state = 'disabled'

    def activate_progressbar(self):
        self.active = True
        self.state = 'active'

        if not self.cron_id:
            nextbackuptime = self.next_backup_time
            if not nextbackuptime:
                nextbackuptime = datetime.datetime.today() + datetime.timedelta(days=1)
            model_id = self.env['ir.model'].search([('model', '=', self._name)])
            cron_id = self.env['ir.cron'].create({
                'name': 'Backup: ' + self.name,
                'model_id': model_id.id,
                'state': 'code',
                'user_id': 1,
                'interval_number': self.schedule_number,
                'interval_type': self.schedule_frequently,
                'nextcall': nextbackuptime,
                'priority': 100,
                'numbercall': -1,
                'active': self.active,
                'code': 'model.action_backup('+str(self.id)+')'
            })
            self.cron_id = cron_id.id
