# -*- coding: utf-8 -*-
'''
Manage IAM roles
================

.. versionadded:: 2014.7.0

This module uses ``boto``, which can be installed via package, or pip.

This module accepts explicit IAM credentials but can also utilize
IAM roles assigned to the instance through Instance Profiles. Dynamic
credentials are then automatically obtained from AWS API and no further
configuration is necessary. More information available `here
<http://docs.aws.amazon.com/AWSEC2/latest/UserGuide/iam-roles-for-amazon-ec2.html>`_.

If IAM roles are not used you need to specify them either in a pillar file or
in the minion's config file:

.. code-block:: yaml

    iam.keyid: GKTADJGHEIQSXMKKRBJ08H
    iam.key: askdjghsdfjkghWupUjasdflkdfklgjsdfjajkghs

It's also possible to specify ``key``, ``keyid`` and ``region`` via a profile, either
passed in as a dict, or as a string to pull from pillars or minion config:

.. code-block:: yaml

    myprofile:
        keyid: GKTADJGHEIQSXMKKRBJ08H
        key: askjghsdfjkghWupUjasdflkdfklgjsdfjajkghs
        region: us-east-1

Creating a role will automatically create an instance profile and associate it
with the role. This is the default behavior of the AWS console.

.. code-block:: yaml

    myrole:
        boto_iam_role.present:
            - region: us-east-1
            - key: GKTADJGHEIQSXMKKRBJ08H
            - keyid: askdjghsdfjkghWupUjasdflkdfklgjsdfjajkghs
            - policies_from_pillars:
                - shared_iam_bootstrap_policy
            - policies:
                MySQSPolicy:
                    Statement:
                      - Action:
                            - sqs:*
                        Effect: Allow
                        Resource:
                            - arn:aws:sqs:*:*:*
                        Sid: MyPolicySQS1
                MyS3Policy:
                    Statement:
                      - Action:
                            - s3:GetObject
                        Effect: Allow
                        Resource:
                            - arn:aws:s3:*:*:mybucket/*

    # Using a credentials profile from pillars
    myrole:
        boto_iam_role.present:
            - profile: myiamprofile

    # Passing in a credentials profile
    myrole:
        boto_iam_role.present:
            - profile:
                key: GKTADJGHEIQSXMKKRBJ08H
                keyid: askdjghsdfjkghWupUjasdflkdfklgjsdfjajkghs
                region: us-east-1

If ``delete_policies: False`` is specified, existing policies that are not in
the given list of policies will not be deleted. This allows manual modifications
on the IAM role to be persistent. This functionality was added in 2015.8.0.
'''
from __future__ import absolute_import
import salt.utils.dictupdate as dictupdate
import salt.ext.six as six


def __virtual__():
    '''
    Only load if boto is available.
    '''
    return 'boto_iam_role' if 'boto_iam.role_exists' in __salt__ else False


def present(
        name,
        policy_document=None,
        path=None,
        policies=None,
        policies_from_pillars=None,
        create_instance_profile=True,
        region=None,
        key=None,
        keyid=None,
        profile=None,
        delete_policies=True):
    '''
    Ensure the IAM role exists.

    name
        Name of the IAM role.

    policy_document
        The policy that grants an entity permission to assume the role. (See http://boto.readthedocs.org/en/latest/ref/iam.html#boto.iam.connection.IAMConnection.create_role)

    path
        The path to the role/instance profile. (See http://boto.readthedocs.org/en/latest/ref/iam.html#boto.iam.connection.IAMConnection.create_role)

    policies
        A dict of IAM role policies.

    policies_from_pillars
        A list of pillars that contain role policy dicts. Policies in the
        pillars will be merged in the order defined in the list and key
        conflicts will be handled by later defined keys overriding earlier
        defined keys. The policies defined here will be merged with the
        policies defined in the policies argument. If keys conflict, the keys
        in the policies argument will override the keys defined in
        policies_from_pillars.

    create_instance_profile
        A boolean of whether or not to create an instance profile and associate
        it with this role.

    region
        Region to connect to.

    key
        Secret key to be used.

    keyid
        Access key to be used.

    profile
        A dict with region, key and keyid, or a pillar key (string)
        that contains a dict with region, key and keyid.

    delete_policies
        Deletes existing policies that are not in the given list of policies. Default
        value is ``True``. If ``False`` is specified, existing policies will not be deleted
        allowing manual modifications on the IAM role to be persistent.

        .. versionadded:: 2015.8.0
    '''
    ret = {'name': name, 'result': True, 'comment': '', 'changes': {}}
    _ret = _role_present(name, policy_document, path, region, key, keyid,
                         profile)
    if not policies:
        policies = {}
    if not policies_from_pillars:
        policies_from_pillars = []
    _policies = {}
    for policy in policies_from_pillars:
        _policy = __salt__['pillar.get'](policy)
        _policies.update(_policy)
    _policies.update(policies)
    ret['changes'] = _ret['changes']
    ret['comment'] = ' '.join([ret['comment'], _ret['comment']])
    if not _ret['result']:
        ret['result'] = _ret['result']
        if ret['result'] is False:
            return ret
    if create_instance_profile:
        _ret = _instance_profile_present(name, region, key, keyid, profile)
        ret['changes'] = dictupdate.update(ret['changes'], _ret['changes'])
        ret['comment'] = ' '.join([ret['comment'], _ret['comment']])
        if not _ret['result']:
            ret['result'] = _ret['result']
            if ret['result'] is False:
                return ret
        _ret = _instance_profile_associated(name, region, key, keyid, profile)
        ret['changes'] = dictupdate.update(ret['changes'], _ret['changes'])
        ret['comment'] = ' '.join([ret['comment'], _ret['comment']])
        if not _ret['result']:
            ret['result'] = _ret['result']
            if ret['result'] is False:
                return ret
    _ret = _policies_present(name, _policies, region, key, keyid, profile,
                             delete_policies)
    ret['changes'] = dictupdate.update(ret['changes'], _ret['changes'])
    ret['comment'] = ' '.join([ret['comment'], _ret['comment']])
    if not _ret['result']:
        ret['result'] = _ret['result']
    return ret


def _role_present(
        name,
        policy_document=None,
        path=None,
        region=None,
        key=None,
        keyid=None,
        profile=None):
    ret = {'result': True, 'comment': '', 'changes': {}}
    role = __salt__['boto_iam.describe_role'](name, region, key, keyid,
                                              profile)
    if not role:
        if __opts__['test']:
            ret['comment'] = 'IAM role {0} is set to be created.'.format(name)
            ret['result'] = None
            return ret
        created = __salt__['boto_iam.create_role'](name, policy_document,
                                                   path, region, key,
                                                   keyid, profile)
        if created:
            ret['changes']['old'] = {'role': None}
            ret['changes']['new'] = {'role': name}
            ret['comment'] = 'IAM role {0} created.'.format(name)
        else:
            ret['result'] = False
            ret['comment'] = 'Failed to create {0} IAM role.'.format(name)
    else:
        ret['comment'] = '{0} role present.'.format(name)
        update_needed = False
        _policy_document = None
        if not policy_document:
            policy = __salt__['boto_iam.build_policy'](region, key, keyid,
                                                       profile)
            if role['assume_role_policy_document'] != policy:
                update_needed = True
                _policy_document = policy
        else:
            if role['assume_role_policy_document'] != policy_document:
                update_needed = True
                _policy_document = policy_document
        if update_needed:
            if __opts__['test']:
                msg = 'Assume role policy document to be updated.'
                ret['comment'] = '{0} {1}'.format(ret['comment'], msg)
                ret['result'] = None
                return ret
            updated = __salt__['boto_iam.update_assume_role_policy'](
                name, _policy_document, region, key, keyid, profile
            )
            if updated:
                msg = 'Assume role policy document updated.'
                ret['comment'] = '{0} {1}'.format(ret['comment'], msg)
                ret['changes']['old'] = {'policy_document': policy_document}
                ret['changes']['new'] = {'policy_document': _policy_document}
            else:
                ret['result'] = False
                msg = 'Failed to update assume role policy.'
                ret['comment'] = '{0} {1}'.format(ret['comment'], msg)
    return ret


def _instance_profile_present(
        name,
        region=None,
        key=None,
        keyid=None,
        profile=None):
    ret = {'result': True, 'comment': '', 'changes': {}}
    exists = __salt__['boto_iam.instance_profile_exists'](name, region, key,
                                                          keyid, profile)
    if not exists:
        if __opts__['test']:
            msg = 'Instance profile {0} is set to be created.'
            ret['comment'] = msg.format(name)
            ret['result'] = None
            return ret
        created = __salt__['boto_iam.create_instance_profile'](name, region,
                                                               key, keyid,
                                                               profile)
        if created:
            ret['changes']['old'] = {'instance_profile': None}
            ret['changes']['new'] = {'instance_profile': name}
            ret['comment'] = 'Instance profile {0} created.'.format(name)
        else:
            ret['result'] = False
            msg = 'Failed to create {0} instance profile.'.format(name)
            ret['comment'] = msg
    return ret


def _instance_profile_associated(
        name,
        region=None,
        key=None,
        keyid=None,
        profile=None):
    ret = {'result': True, 'comment': '', 'changes': {}}
    is_associated = __salt__['boto_iam.profile_associated'](name, name, region,
                                                            key, keyid,
                                                            profile)
    if not is_associated:
        if __opts__['test']:
            msg = 'Instance profile {0} is set to be associated.'
            ret['comment'] = msg.format(name)
            ret['result'] = None
            return ret
        associated = __salt__['boto_iam.associate_profile_to_role'](name, name,
                                                                    region,
                                                                    key, keyid,
                                                                    profile)
        if associated:
            ret['changes']['old'] = {'profile_associated': None}
            ret['changes']['new'] = {'profile_associated': True}
            ret['comment'] = 'Instance profile {0} associated.'.format(name)
        else:
            ret['result'] = False
            msg = 'Failed to associate {0} instance profile with {0} role.'
            ret['comment'] = msg.format(name)
    return ret


def _policies_present(
        name,
        policies=None,
        region=None,
        key=None,
        keyid=None,
        profile=None,
        delete_policies=True):
    ret = {'result': True, 'comment': '', 'changes': {}}
    policies_to_create = {}
    policies_to_delete = []
    for policy_name, policy in six.iteritems(policies):
        _policy = __salt__['boto_iam.get_role_policy'](name, policy_name,
                                                       region, key, keyid,
                                                       profile)
        if _policy != policy:
            policies_to_create[policy_name] = policy
    _list = __salt__['boto_iam.list_role_policies'](name, region, key, keyid,
                                                    profile)
    for policy_name in _list:
        if delete_policies and policy_name not in policies:
            policies_to_delete.append(policy_name)
    if policies_to_create or policies_to_delete:
        _to_modify = list(policies_to_delete)
        _to_modify.extend(policies_to_create)
        if __opts__['test']:
            msg = '{0} policies to be modified on role {1}.'
            ret['comment'] = msg.format(', '.join(_to_modify), name)
            ret['result'] = None
            return ret
        ret['changes']['old'] = {'policies': _list}
        for policy_name, policy in six.iteritems(policies_to_create):
            policy_set = __salt__['boto_iam.create_role_policy'](name,
                                                                 policy_name,
                                                                 policy,
                                                                 region, key,
                                                                 keyid,
                                                                 profile)
            if not policy_set:
                _list = __salt__['boto_iam.list_role_policies'](name, region,
                                                                key, keyid,
                                                                profile)
                ret['changes']['new'] = {'policies': _list}
                ret['result'] = False
                msg = 'Failed to add policy {0} to role {1}'
                ret['comment'] = msg.format(policy_name, name)
                return ret
        for policy_name in policies_to_delete:
            policy_unset = __salt__['boto_iam.delete_role_policy'](name,
                                                                   policy_name,
                                                                   region, key,
                                                                   keyid,
                                                                   profile)
            if not policy_unset:
                _list = __salt__['boto_iam.list_role_policies'](name, region,
                                                                key, keyid,
                                                                profile)
                ret['changes']['new'] = {'policies': _list}
                ret['result'] = False
                msg = 'Failed to remove policy {0} from role {1}'
                ret['comment'] = msg.format(policy_name, name)
                return ret
        _list = __salt__['boto_iam.list_role_policies'](name, region, key,
                                                        keyid, profile)
        ret['changes']['new'] = {'policies': _list}
        msg = '{0} policies modified on role {1}.'
        ret['comment'] = msg.format(', '.join(_list), name)
    return ret


def absent(
        name,
        region=None,
        key=None,
        keyid=None,
        profile=None):
    '''
    Ensure the IAM role is deleted.

    name
        Name of the IAM role.

    region
        Region to connect to.

    key
        Secret key to be used.

    keyid
        Access key to be used.

    profile
        A dict with region, key and keyid, or a pillar key (string)
        that contains a dict with region, key and keyid.
    '''
    ret = {'name': name, 'result': True, 'comment': '', 'changes': {}}
    _ret = _policies_absent(name, region, key, keyid, profile)
    ret['changes'] = _ret['changes']
    ret['comment'] = ' '.join([ret['comment'], _ret['comment']])
    if not _ret['result']:
        ret['result'] = _ret['result']
        if ret['result'] is False:
            return ret
    _ret = _instance_profile_disassociated(name, region, key, keyid, profile)
    ret['changes'] = dictupdate.update(ret['changes'], _ret['changes'])
    ret['comment'] = ' '.join([ret['comment'], _ret['comment']])
    if not _ret['result']:
        ret['result'] = _ret['result']
        if ret['result'] is False:
            return ret
    _ret = _instance_profile_absent(name, region, key, keyid, profile)
    ret['changes'] = dictupdate.update(ret['changes'], _ret['changes'])
    ret['comment'] = ' '.join([ret['comment'], _ret['comment']])
    if not _ret['result']:
        ret['result'] = _ret['result']
        if ret['result'] is False:
            return ret
    _ret = _role_absent(name, region, key, keyid, profile)
    ret['changes'] = dictupdate.update(ret['changes'], _ret['changes'])
    ret['comment'] = ' '.join([ret['comment'], _ret['comment']])
    if not _ret['result']:
        ret['result'] = _ret['result']
    return ret


def _role_absent(
        name,
        region=None,
        key=None,
        keyid=None,
        profile=None):
    ret = {'result': True, 'comment': '', 'changes': {}}

    exists = __salt__['boto_iam.role_exists'](name, region, key, keyid,
                                              profile)
    if exists:
        if __opts__['test']:
            ret['comment'] = 'IAM role {0} is set to be removed.'.format(
                name)
            ret['result'] = None
            return ret
        deleted = __salt__['boto_iam.delete_role'](name, region, key, keyid,
                                                   profile)
        if deleted:
            ret['changes']['old'] = {'role': name}
            ret['changes']['new'] = {'role': None}
            ret['comment'] = 'IAM role {0} removed.'.format(name)
        else:
            ret['result'] = False
            ret['comment'] = 'Failed to delete {0} iam role.'.format(name)
    else:
        ret['comment'] = '{0} role does not exist.'.format(name)
    return ret


def _instance_profile_absent(
        name,
        region=None,
        key=None,
        keyid=None,
        profile=None):
    ret = {'result': True, 'comment': '', 'changes': {}}

    exists = __salt__['boto_iam.instance_profile_exists'](name, region, key,
                                                          keyid, profile)
    if exists:
        if __opts__['test']:
            msg = 'Instance profile {0} is set to be removed.'
            ret['comment'] = msg.format(name)
            ret['result'] = None
            return ret
        deleted = __salt__['boto_iam.delete_instance_profile'](name, region,
                                                               key, keyid,
                                                               profile)
        if deleted:
            ret['changes']['old'] = {'instance_profile': name}
            ret['changes']['new'] = {'instance_profile': None}
            ret['comment'] = 'Instance profile {0} removed.'.format(name)
        else:
            ret['result'] = False
            msg = 'Failed to delete {0} instance profile.'.format(name)
            ret['comment'] = msg
    else:
        ret['comment'] = '{0} instance profile does not exist.'.format(name)
    return ret


def _policies_absent(
        name,
        region=None,
        key=None,
        keyid=None,
        profile=None):
    ret = {'result': True, 'comment': '', 'changes': {}}
    _list = __salt__['boto_iam.list_role_policies'](name, region, key, keyid,
                                                    profile)
    if not _list:
        msg = 'No policies in role {0}.'.format(name)
        ret['comment'] = msg
        return ret
    if __opts__['test']:
        msg = '{0} policies to be removed from role {1}.'
        ret['comment'] = msg.format(', '.join(_list), name)
        ret['result'] = None
        return ret
    ret['changes']['old'] = {'policies': _list}
    for policy_name in _list:
        policy_unset = __salt__['boto_iam.delete_role_policy'](name,
                                                               policy_name,
                                                               region, key,
                                                               keyid,
                                                               profile)
        if not policy_unset:
            _list = __salt__['boto_iam.list_role_policies'](name, region,
                                                            key, keyid,
                                                            profile)
            ret['changes']['new'] = {'policies': _list}
            ret['result'] = False
            msg = 'Failed to add policy {0} to role {1}'
            ret['comment'] = msg.format(policy_name, name)
            return ret
    _list = __salt__['boto_iam.list_role_policies'](name, region, key,
                                                    keyid, profile)
    ret['changes']['new'] = {'policies': _list}
    msg = '{0} policies removed from role {1}.'
    ret['comment'] = msg.format(', '.join(_list), name)
    return ret


def _instance_profile_disassociated(
        name,
        region=None,
        key=None,
        keyid=None,
        profile=None):
    ret = {'result': True, 'comment': '', 'changes': {}}
    is_associated = __salt__['boto_iam.profile_associated'](name, name, region,
                                                            key, keyid,
                                                            profile)
    if is_associated:
        if __opts__['test']:
            msg = 'Instance profile {0} is set to be disassociated.'
            ret['comment'] = msg.format(name)
            ret['result'] = None
            return ret
        associated = __salt__['boto_iam.disassociate_profile_from_role'](name, name, region, key, keyid, profile)
        if associated:
            ret['changes']['old'] = {'profile_associated': True}
            ret['changes']['new'] = {'profile_associated': False}
            msg = 'Instance profile {0} disassociated.'.format(name)
            ret['comment'] = msg
        else:
            ret['result'] = False
            msg = 'Failed to disassociate {0} instance profile from {0} role.'
            ret['comment'] = msg.format(name)
    return ret
