#!/usr/bin/env python

#
# threat_note v3.0                                      #
# Developed By: Brian Warehime                          #
# Defense Point Security (defpoint.com)                 #
# October 26, 2015                                      #
#

import csv
import hashlib
import io
import re
import sqlite3 as lite
import time
import urllib
import argparse

import libs.circl
import libs.cuckoo
import libs.farsight
import libs.helpers
import libs.investigate
import libs.passivetotal
import libs.shodan
import libs.whoisinfo
import libs.virustotal


from flask import Flask
from flask import flash
from flask import jsonify
from flask import make_response
from flask import redirect
from flask import render_template
from flask import request
from flask import url_for
from flask.ext.login import current_user
from flask.ext.login import LoginManager
from flask.ext.login import login_required
from flask.ext.login import login_user
from flask.ext.login import logout_user
from flask.ext.wtf import Form

from werkzeug.datastructures import ImmutableMultiDict
from wtforms import PasswordField
from wtforms import StringField
from wtforms.validators import DataRequired

from libs.models import User, Setting, Indicator
from libs.database import db_session
from libs.database import init_db
#from sqlalchemy import distinct


#
# Configuration #
#


app = Flask(__name__)
app.config['SECRET_KEY'] = 'yek_terces'
lm = LoginManager()
lm.init_app(app)
lm.login_view = 'login'

class LoginForm(Form):
    user = StringField('user', validators=[DataRequired()])
    password = PasswordField('password', validators=[DataRequired()])

    def get_user(self):
        return db_session.query(User).filter_by(user=self.user.data.lower(), password=hashlib.md5(self.password.data.encode('utf-8')).hexdigest()).first()


class RegisterForm(Form):
    user = StringField('user', validators=[DataRequired()])
    password = PasswordField('password', validators=[DataRequired()])
    email = StringField('email')


#
# Creating routes #
#

@lm.user_loader
def load_user(id):
    return db_session.query(User).filter_by(_id=id).first()


@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        user = db_session.query(User).filter_by(user=form.user.data.lower()).first()
        if user:
            flash('User exists.')
        else:
            user = User(form.user.data.lower(), form.password.data, form.email.data)
            db_session.add(user)
            db_session.commit()

            login_user(user)

    if current_user.is_authenticated:
        return redirect(url_for('home'))

    return render_template('register.html', form=form, title='Register')


@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = form.get_user()
        if not user:
            flash('Invalid User or Key.')
        else:
            login_user(user)

    if current_user.is_authenticated:
        return redirect(url_for('home'))

    return render_template('login.html', form=form, title='Login')


@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('login'))


@app.route('/', methods=['GET'])
@login_required
def home():
    try:
        counts = Indicator.query.distinct(Indicator._id).count()
        types = Indicator.query.distinct(Indicator.type).group_by(Indicator.type).all()
        network = Indicator.query.order_by(Indicator._id).limit(5).all()
        campaigns = Indicator.query.distinct(Indicator.campaign).all()
        taglist = Indicator.query.distinct(Indicator.tags).all()

        #cur.execute("SELECT count(DISTINCT id) AS number FROM indicators")
        #counts = cur.fetchall()

        #cur.execute( "SELECT type, COUNT(*) AS `num` FROM indicators GROUP BY type")
        #types = cur.fetchall()

        #cur.execute("SELECT DISTINCT campaign FROM indicators")
        #networks = cur.fetchall()


        # Generate Tag Cloud
        tags = []
        for object in taglist:
            if object.tags == "":
                pass
            else:
                for tag in object.tags.split(","):
                    tags.append(tag.strip())
        newtags = []
        for i in tags:
              if i not in newtags:
                   newtags.append(i.strip())

        dictcount = {}
        dictlist = []
        typecount = {}
        typelist = []

        # Generate Campaign Statistics Graph
        test = {}
        for object in campaigns:
            campcount = Indicator.query.filter(Indicator.campaign == object.campaign).count()
            #cur.execute(
            #    "select count(_id) FROM indicators WHERE campaign = '" + object.campaign + "'")


            if object.campaign == '':
                dictcount["category"] = "Unknown"
                tempx = (float(campcount) / float(counts)) * 100
                dictcount["value"] = round(tempx, 2)
            else:
                dictcount["category"] = object.campaign
                tempx = (float(campcount) / float(counts)) * 100
                dictcount["value"] = round(tempx, 2)

            dictlist.append(dictcount.copy())

        # Generate Indicator Type Graph
        for t in types:
            typecount["category"] = t.type
            tempx = float(len(types)) / float(counts)
            newtemp = tempx * 100
            typecount["value"] = round(newtemp, 2)
            typelist.append(typecount.copy())
        favs = []

        # Add Import from Cuckoo button to Dashboard page
        settings = Setting.query.filter_by(_id=1).first()
        if 'on' in settings.cuckoo:
            importsetting = True
        else:
            importsetting = False

        return render_template('dashboard.html', networks=dictlist, network=network, favs=favs, typelist=typelist,
                               taglist=newtags, importsetting=importsetting)
    except Exception as e:
        return render_template('error.html', error=e)


@app.route('/about', methods=['GET'])
@login_required
def about():
    return render_template('about.html')

@app.route('/tags', methods=['GET'])
@login_required
def tags():
    try:
        tags = []
        taglist = Indicator.query.distinct(Indicator.tags).all()
        for object in taglist:
            if object.tags == "":
                pass
            else:
                for tag in object.tags.split(","):
                    tags.append(tag.strip())
        campaignents = {}
        for tag in tags:
            entlist = []
            camps = Indicator.query.filter(Indicator.tags.in_((tag)))
            for ent in camps:
                entlist.append(ent)
            campaignents[str(tag)] = entlist
        return render_template('tags.html', tags=campaignents)
    except Exception as e:
        return render_template('error.html', error=e)

@app.route('/networks', methods=['GET'])
@login_required
def networks():
    try:
        # Grab only network indicators
        network = Indicator.query.filter(Indicator.type.in_(('IPv4', 'IPv6', 'Domain', 'Network'))).all()
        return render_template('networks.html', network=network)
    except Exception as e:
        return render_template('error.html', error=e)


@app.route('/threatactors', methods=['GET'])
@login_required
def threatactors():
    try:
        # Grab threat actors
        threatactors = Indicator.query.filter(Indicator.type == ('Threat Actor')).all()
        return render_template('threatactors.html', network=threatactors)
    except Exception as e:
        return render_template('error.html', error=e)


@app.route('/victims', methods=['GET'])
@login_required
def victims():
    try:
        # Grab victims
        victims = Indicator.query.filter(Indicator.diamondmodel == ('Victim')).all()
        return render_template('victims.html', network=victims)
    except Exception as e:
        return render_template('error.html', error=e)

@app.route('/files', methods=['GET'])
@login_required
def files():
    try:
        # Grab files/hashes
        files = Indicator.query.filter(Indicator.type == ('Hash')).all()
        return render_template('files.html', network=files)
    except Exception as e:
        return render_template('error.html', error=e)


@app.route('/campaigns', methods=['GET'])
@login_required
def campaigns():
    try:
        # Grab campaigns
        campaignents = dict()
        rows = Indicator.query.group_by(Indicator.campaign).all()
        for c in rows:
            if c.campaign == '':
                name = 'Unknown'
            else:
                name = c.campaign
            campaignents[name] = list()
        # Match indicators to campaigns
        for camp, indicators in campaignents.iteritems():
            if camp == 'Unknown':
                camp = ''
            rows = Indicator.query.filter(Indicator.campaign == camp).all()
            tmp = {}
            for i in rows:
                tmp[i.object] = i.type
                indicators.append(tmp)
        return render_template('campaigns.html', campaignents=campaignents)
    except Exception as e:
        return render_template('error.html', error=e)


@app.route('/settings', methods=['GET'])
@login_required
def settings():
    try:
        settings = Setting.query.filter_by(_id=1).all()
        if settings == []:
            settings = Setting('', '', 'off', 'off', 'off', 'off', 'off', 'off', 'off', 'off', 'off', 'off', 'off', 'off',
                               'off', 'off', 'off', 'off', 'off', 'off')
            db_session.add(settings)
            db_session.commit()
        settings = Setting.query.filter_by(_id=1).first()

        return render_template('settings.html', records=settings)
    except Exception as e:
        return render_template('error.html', error=e)


@app.route('/campaign/<uid>/info', methods=['GET'])
@login_required
def campaignsummary(uid):
    try:
        http = Indicator.query.filter_by(object=uid).first()
        # Run ipwhois or domainwhois based on the type of indicator
        if str(http.type) == "IPv4" or str(http.type) == "IPv6" or str(
                http.type) == "Domain" or str(http.type) == "Network":
            return redirect(url_for('objectsummary', uid=http.object))
        elif str(http.type) == "Hash":
            return redirect(url_for('filesobject', uid=http.object))
        else:
            return redirect(url_for('threatactorobject', uid=http.object))
    except Exception as e:
        return render_template('error.html', error=e)


@app.route('/newobject', methods=['GET'])
@login_required
def newobj():
    try:
        currentdate = time.strftime("%Y-%m-%d")
        return render_template('newobject.html', currentdate=currentdate)
    except Exception as e:
        return render_template('error.html', error=e)


@app.route('/insert/object/', methods=['POST'])
@login_required
def newobject():
    try:
        something = request.form
        imd = ImmutableMultiDict(something)
        records = libs.helpers.convert(imd)
        newdict = {}
        for i in records:
            newdict[i] = records[i]

        # Import indicators from Cuckoo for the selected analysis task

        if records.has_key('type') and 'cuckoo' in records['type']:
            con = libs.helpers.db_connection()

            host_data, dns_data, sha1, firstseen = libs.cuckoo.report_data(records['cuckoo_task_id'])
            if not None in (host_data, dns_data, sha1, firstseen):
                # Import IP Indicators from Cuckoo Task
                for ip in host_data:
                    object = Indicator.query.filter_by(object=ip).first()
                    if object is None:
                        indicator = Indicator(ip.strip(), 'IPv4', firstseen, '', 'Infrastructure', records['campaign'],
                                 'Low', '', newdict['tags'], '')
                        db_session.add(indicator)
                        db_session.commit()
                    else:
                        errormessage = "Entry already exists in database."
                        return render_template('newobject.html', errormessage=errormessage,
                                               inputtype=newdict['inputtype'], inputobject=ip,
                                               inputfirstseen=newdict['inputfirstseen'],
                                               inputlastseen=newdict['inputlastseen'],
                                               inputcampaign=newdict['inputcampaign'],
                                               comments=newdict['comments'],
                                               diamondmodel=newdict['diamondmodel'],
                                               tags=newdict['tags'])
                    # Import Domain Indicators from Cuckoo Task
                    for dns in dns_data:
                        object = Indicator.query.filter_by(object=dns['requst']).first()
                        if object is None:
                            indicator = Indicator(dns['request'], 'Domain', firstseen, '', 'Infrastructure',
                                                  records['campaign'], 'Low', '', newdict['tags'], '')
                            db_session.add(indicator)
                            db_session.commit()
                        else:
                            errormessage = "Entry already exists in database."
                            return render_template('newobject.html', errormessage=errormessage,
                                                   inputtype=newdict['inputtype'], inputobject=ip,
                                                   inputfirstseen=newdict['inputfirstseen'],
                                                   inputlastseen=newdict['inputlastseen'],
                                                   inputcampaign=newdict['inputcampaign'],
                                                   comments=newdict['comments'],
                                                   diamondmodel=newdict['diamondmodel'],
                                                   tags=newdict['tags'])
                    # Import File/Hash Indicators from Cuckoo Task
                    object = Indicator.query.filter_by(object=sha1).first()
                    if object is None:
                        indicator = Indicator(sha1, 'Hash', firstseen, '', 'Capability',
                                              records['campaign'], 'Low', '', newdict['tags'], '')
                        db_session.add(indicator)
                        db_session.commit()
                    else:
                        errormessage = "Entry already exists in database."
                        return render_template('newobject.html', errormessage=errormessage,
                                               inputtype=newdict['inputtype'], inputobject=ip,
                                               inputfirstseen=newdict['inputfirstseen'],
                                               inputlastseen=newdict['inputlastseen'],
                                               inputcampaign=newdict['inputcampaign'],
                                               comments=newdict['comments'],
                                               diamondmodel=newdict['diamondmodel'],
                                               tags=newdict['tags'])

                # Redirect to Dashboard after successful import
                return redirect(url_for('home'))
            else:
                errormessage = 'Task is not a file analysis'
                return redirect(url_for('import_indicators'))

        if records.has_key('inputtype'):
            # Makes sure if you submit an IPv4 indicator, it's an actual IP
            # address.
            ipregex = re.match(
                r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}', newdict['inputobject'])
            # Convert the inputobject of IP or Domain to a list for Bulk Add functionality.
            newdict['inputobject'] = newdict['inputobject'].split(',')
            for newobject in newdict['inputobject']:
                if newdict['inputtype'] == "IPv4":
                    if ipregex:
                        object = Indicator.query.filter_by(object=newobject).first()
                        if object is None:
                            ipv4_indicator = Indicator(newobject.strip(), newdict['inputtype'], newdict['inputfirstseen'],
                                     newdict['inputlastseen'], newdict['diamondmodel'], newdict['inputcampaign'],
                                     newdict['confidence'], newdict['comments'], newdict['tags'], None)
                            db_session.add(ipv4_indicator)
                            db_session.commit()
                            network = Indicator.query.filter(Indicator.type.in_(('IPv4', 'IPv6', 'Domain', 'Network'))).all()
                        else:
                            errormessage = "Entry already exists in database."
                            return render_template('newobject.html', errormessage=errormessage,
                                                   inputtype=newdict['inputtype'], inputobject=newobject,
                                                   inputfirstseen=newdict['inputfirstseen'],
                                                   inputlastseen=newdict['inputlastseen'],
                                                   inputcampaign=newdict['inputcampaign'],
                                                   comments=newdict['comments'],
                                                   diamondmodel=newdict['diamondmodel'],
                                                   tags=newdict['tags'])

                    else:
                        errormessage = "Not a valid IP Address."
                        newobject = ', '.join(newdict['inputobject'])
                        return render_template('newobject.html', errormessage=errormessage,
                                               inputtype=newdict['inputtype'],
                                               inputobject=newobject, inputfirstseen=newdict['inputfirstseen'],
                                               inputlastseen=newdict['inputlastseen'],
                                               confidence=newdict['confidence'], inputcampaign=newdict['inputcampaign'],
                                               comments=newdict['comments'], diamondmodel=newdict['diamondmodel'],
                                               tags=newdict['tags'])
                else:
                    object = Indicator.query.filter_by(object=newobject).first()
                    if object is None:
                        indicator = Indicator(newobject.strip(), newdict['inputtype'], newdict['inputfirstseen'],
                                 newdict['inputlastseen'], newdict['diamondmodel'], newdict['inputcampaign'],
                                 newdict['confidence'], newdict['comments'], newdict['tags'], None)
                        db_session.add(indicator)
                        db_session.commit()
                    else:
                        errormessage = "Entry already exists in database."
                        return render_template('newobject.html', errormessage=errormessage,
                                               inputtype=newdict['inputtype'], inputobject=newobject,
                                               inputfirstseen=newdict['inputfirstseen'],
                                               inputlastseen=newdict['inputlastseen'],
                                               inputcampaign=newdict['inputcampaign'],
                                               comments=newdict['comments'],
                                               diamondmodel=newdict['diamondmodel'],
                                               tags=newdict['tags'])

            # TODO: Change 'network' to 'object' in HTML templates to standardize on verbiage
            if newdict['inputtype'] == "IPv4" or newdict['inputtype'] == "Domain" or newdict[
                    'inputtype'] == "Network" or newdict['inputtype'] == "IPv6":
                network = Indicator.query.filter(Indicator.type.in_(('IPv4', 'IPv6', 'Domain', 'Network'))).all()
                return render_template('networks.html', network=network)

            elif newdict['diamondmodel'] == "Victim":
                victims = Indicator.query.filter(Indicator.diamondmodel == ('Victim')).all()
                return render_template('victims.html', network=victims)

            elif newdict['inputtype'] == "Hash":
                files = Indicator.query.filter(Indicator.type == ('Hash')).all()
                return render_template('files.html', network=files)

            else:
                threatactors = Indicator.query.filter(Indicator.type == ('Threat Actors')).all()
                return render_template('threatactors.html', network=threatactors)

    except Exception as e:
        return render_template('error.html', error=e)


@app.route('/edit/<uid>', methods=['POST', 'GET'])
@login_required
def editobject(uid):
    try:
        http = Indicator.query.filter(Indicator.object == uid).first()
        newdict = libs.helpers.row_to_dict(http)

        return render_template('neweditobject.html', entry=newdict)
    except Exception as e:
        return render_template('error.html', error=e)


@app.route('/delete/network/<uid>', methods=['GET'])
@login_required
def deletenetworkobject(uid):
    try:
        Indicator.query.filter_by(object=uid).delete()
        db_session.commit()
        network = Indicator.query.filter(Indicator.type.in_(('IPv4', 'IPv6', 'Domain', 'Network'))).all()
        return render_template('networks.html', network=network)
    except Exception as e:
        return render_template('error.html', error=e)


@app.route('/delete/threatactor/<uid>', methods=['GET'])
@login_required
def deletethreatactorobject(uid):
    try:
        Indicator.query.filter_by(object=uid).delete()
        db_session.commit()
        threatactors = Indicator.query.filter_by(type='Threat Actor')
        return render_template('threatactors.html', network=threatactors)
    except Exception as e:
        return render_template('error.html', error=e)


@app.route('/delete/victims/<uid>', methods=['GET'])
@login_required
def deletevictimobject(uid):
    try:
        Indicator.query.filter_by(object=uid).delete()
        db_session.commit()
        victims = Indicator.query.filter_by(diamondmodel='Victim')
        return render_template('victims.html', network=victims)
    except Exception as e:
        return render_template('error.html', error=e)


@app.route('/delete/files/<uid>', methods=['GET'])
@login_required
def deletefilesobject(uid):
    try:
        Indicator.query.filter_by(object=uid).delete()
        db_session.commit()
        files = Indicator.query.filter_by(type='Hash')

        return render_template('victims.html', network=files)
    except Exception as e:
        return render_template('error.html', error=e)

@app.route('/update/settings/', methods=['POST'])
@login_required
def updatesettings():
    try:
        something = request.form
        imd = ImmutableMultiDict(something)
        newdict = libs.helpers.convert(imd)
        settings = Setting.query.filter_by(_id=1).first()

        # Make sure we're updating the settings instead of overwriting them
        if 'threatcrowd' in newdict.keys():
            settings.threatcrowd = 'on'
        else:
           settings.threatcrowd = 'off'
        if 'ptinfo' in newdict.keys():
            settings.ptinfo = 'on'
        else:
            settings.ptinfo = 'off'
        if 'cuckoo' in newdict.keys():
            settings.cuckoo = 'on'
        else:
            settings.cuckoo = 'off'
        if 'vtinfo' in newdict.keys():
            settings.vtinfo = 'on'
        else:
            settings.vtinfo = 'off'
        if 'vtfile' in newdict.keys():
            settings.vtfile = 'on'
        else:
            settings.vtfile = 'off'
        if 'circlinfo' in newdict.keys():
            settings.circlinfo = 'on'
        else:
            settings.circlinfo = 'off'
        if 'circlssl' in newdict.keys():
            settings.circlssl = 'on'
        else:
            settings.circlssl = 'off'
        if 'whoisinfo' in newdict.keys():
            settings.whoisinfo = 'on'
        else:
            settings.whoisinfo = 'off'
        if 'farsightinfo' in newdict.keys():
            settings.farsightinfo = 'on'
        else:
            settings.farsightinfo = 'off'
        if 'odnsinfo' in newdict.keys():
            settings.odnsinfo = 'on'
        else:
            settings.odnsinfo = 'off'

        settings.farsightkey = newdict['farsightkey']
        settings.apikey = newdict['apikey']
        settings.odnskey = newdict['odnskey']
        settings.httpproxy = newdict['httpproxy']
        settings.httpsproxy = newdict['httpsproxy']
        settings.cuckoohost = newdict['cuckoohost']
        settings.cuckooapiport = newdict['cuckooapiport']
        settings.circlusername = newdict['circlusername']
        settings.circlpassword = newdict['circlpassword']
        settings.ptkey = newdict['ptkey']

        db_session.commit()
        settings = Setting.query.first()

        return render_template('settings.html', records=settings)
    except Exception as e:
        return render_template('error.html', error=e)


@app.route('/update/object/', methods=['POST'])
@login_required
def updateobject():
    try:
        # Updates entry information
        something = request.form
        imd = ImmutableMultiDict(something)
        records = libs.helpers.convert(imd)
        taglist = records['tags'].split(",")

        indicator = Indicator.query.filter_by(object=records['object']).first()


        try:
            Indicator.query.filter_by(object=records['object']).update(records)
        except Exception as e:
            # SQLAlchemy does not outright support altering tables.
            for k,v in records.iteritems():
                if Indicator.query.group_by(k).first() is None:
                    print 'ALTER Table'
                    #db_session.engine.execute("ALTER TABLE indicators ADD COLUMN " + k + " TEXT DEFAULT ''")

        db_session.commit()

           # db_session.execute('ALTER  TABLE indicators ADD COLUMN')

        #con = libs.helpers.db_connection()
        #with con:
        #    cur = con.cursor()
        #    cur.execute(
        #        "ALTER TABLE indicators ADD COLUMN " + t + " TEXT DEFAULT ''")
        #    cur.execute("UPDATE indicators SET " + t + "= '" + records[
        #                t] + "' WHERE id = '" + records['id'] + "'")

        if records['type'] == "IPv4" or records['type'] == "IPv6" or records['type'] == "Domain" or records['type'] == "Network":
            return redirect(url_for('objectsummary', uid=str(records['object'])))
        elif records['type'] ==  "Hash":
            return redirect(url_for('filesobject', uid=str(records['object'])))
        elif records['type'] == "Entity":
            return redirect(url_for('victimobject', uid=str(records['object'])))
        elif records['type'] == "Threat Actor":
            return redirect(url_for('threatactorobject', uid=str(records['object'])))
    except Exception as e:
        return render_template('error.html', error=e)


@app.route('/insert/newfield/', methods=['POST'])
@login_required
def insertnewfield():
    try:
        something = request.form
        imd = ImmutableMultiDict(something)
        records = libs.helpers.convert(imd)
        newdict = {}
        for i in records:
            if i == "inputnewfieldname":
                newdict[records[i]] = records['inputnewfieldvalue']
            elif i == "inputnewfieldvalue":
                pass
            else:
                newdict[i] = records[i]
        return render_template('neweditobject.html', entry=newdict)
    except Exception as e:
        return render_template('error.html', error=e)


@app.route('/network/<uid>/info', methods=['GET'])
@login_required
def objectsummary(uid):
    try:
        http = Indicator.query.filter(Indicator.object == uid).first()
        newdict = libs.helpers.row_to_dict(http)
        settings = Setting.query.filter_by(_id=1).first()
        taglist = http.tags.split(",")

        temprel = {}
        if http.relationships:
            rellist = http.relationships.split(",")
            for rel in rellist:
                reltype = Indicator.query.filter(Indicator.object == rel)
                temprel[reltype.object] = reltype.type

        reldata = len(temprel)
        jsonvt = ""
        whoisdata = ""
        odnsdata = ""
        circldata = ""
        circlssl = ""
        ptdata = ""
        farsightdata = ""
        shodandata = ""
        # Run ipwhois or domainwhois based on the type of indicator
        if str(http.type) == "IPv4" or str(http.type) == "IPv6":
            if settings.vtinfo == "on":
                jsonvt = libs.virustotal.vt_ipv4_lookup(str(http.object))
            if settings.whoisinfo == "on":
                whoisdata = libs.whoisinfo.ipwhois(str(http.object))
            if settings.odnsinfo == "on":
                odnsdata = libs.investigate.ip_query(str(http.object))
            if settings.circlinfo == "on":
                circldata = libs.circl.circlquery(str(http.object))
            if settings.circlssl == "on":
                circlssl = libs.circl.circlssl(str(http.object))
            if settings.ptinfo == "on":
                ptdata = libs.passivetotal.pt(str(http.object))
            if settings.farsightinfo == "on":
                farsightdata = libs.farsight.farsightip(str(http.object))
        elif str(http.type) == "Domain":
            if settings.whoisinfo == "on":
                whoisdata = libs.whoisinfo.domainwhois(str(http.object))
            if settings.vtinfo == "on":
                jsonvt = libs.virustotal.vt_domain_lookup(str(http.object))
            if settings.odnsinfo == "on":
                odnsdata = libs.investigate.domain_categories(str(http.object))
            if settings.circlinfo == "on":
                circldata = libs.circl.circlquery(str(http.object))
            if settings.ptinfo == "on":
                ptdata = libs.passivetotal.pt(str(http.object))
            if settings.farsightinfo == "on":
                farsightdata = libs.farsight.farsightdomain(str(http.object))
        if settings.whoisinfo == "on":
            if str(http.type) == "Domain":
                address = str(whoisdata['city']) + ", " + str(whoisdata['country'])
            else:
                address = str(whoisdata['nets'][0]['city']) + ", " + str(
                    whoisdata['nets'][0]['country'])
        else:
            address = "Information about " + str(http.object)
        return render_template('networkobject.html', records=newdict, jsonvt=jsonvt, whoisdata=whoisdata,
            odnsdata=odnsdata, settingsvars=settings, address=address, ptdata=ptdata, temprel=temprel, circldata=circldata,
            circlssl=circlssl, reldata=reldata, taglist=taglist, farsightdata=farsightdata)
    except Exception as e:
        return render_template('error.html', error=e)


@app.route('/threatactors/<uid>/info', methods=['GET'])
@login_required
def threatactorobject(uid):
    try:
        http = Indicator.query.filter(Indicator.object == uid).first()
        newdict = libs.helpers.row_to_dict(http)

        temprel = {}
        if http.relationships:
            rellist = http.relationships.split(",")
            for rel in rellist:
                reltype = Indicator.query.filter(Indicator.object == rel)
                temprel[reltype.object] = reltype.type

        reldata = len(temprel)
        return render_template('threatactorobject.html', records=newdict, temprel=temprel, reldata=reldata)
    except Exception as e:
        return render_template('error.html', error=e)

@app.route('/relationships/<uid>', methods=['GET'])
@login_required
def relationships(uid):
    try:
        http = Indicator.query.filter_by(object=uid).first()
        indicators = Indicator.query.all()
        rels = Indicator.query.filter_by(object=uid).first()
        if http.relationships:
            rellist = rels.split(",")
            temprel = {}
            for rel in rellist:
                reltype = Indicator.query.filter_by(object=rel).first()
                temprel[reltype['object']] = reltype['type']
        return render_template('addrelationship.html', records=http, indicators=indicators)
    except Exception as e:
        return render_template('error.html', error=e)


@app.route('/addrelationship', methods=['GET', 'POST'])
@login_required
def addrelationship():
    try:
        something = request.form
        imd = ImmutableMultiDict(something)
        records = libs.helpers.convert(imd)
        #newdict = {}
        #for i in records:
        #    newdict[i] = records[i]

        con = libs.helpers.db_connection()
        with con:
            cur = con.cursor()
            stm = "UPDATE indicators SET relationships=relationships || '" + records['indicator'] + ",' WHERE object='" + records['id'] + "'"
            cur.execute("UPDATE indicators SET relationships=relationships || '" + records['indicator'] + ",' WHERE object='" + records['id'] + "'")


        if records['type'] == "IPv4" or records['type'] == "IPv6" or records['type'] == "Domain" or records['type'] == "Network":
            return redirect(url_for('objectsummary', uid=str(records['id'])))
        elif records['type'] ==  "Hash":
            return redirect(url_for('filesobject', uid=str(records['id'])))
        elif records['type'] == "Entity":
            return redirect(url_for('victimobject', uid=str(records['id'])))
        elif records['type'] == "Threat Actor":
            return redirect(url_for('threatactorobject', uid=str(records['id'])))
    except Exception as e:
        return render_template('error.html', error=e)


@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    try:
        user = User.query.filter_by(user=current_user.user.lower()).first()
        something = request.form
        imd = ImmutableMultiDict(something)
        records = libs.helpers.convert(imd)

        if 'currentpw' in records:
            if hashlib.md5(records['currentpw'].encode('utf-8')).hexdigest() == user.password:
                if records['newpw'] == records['newpwvalidation']:
                    user.password = hashlib.md5(records['newpw'].encode('utf-8')).hexdigest()
                    db_session.commit()
                    errormessage = "Password updated successfully."
                    return render_template('profile.html', errormessage=errormessage)
                else:
                    errormessage = "New passwords don't match."
                    return render_template('profile.html', errormessage=errormessage)
            else:
                errormessage = "Current password is incorrect."
                return render_template('profile.html', errormessage=errormessage)
        return render_template('profile.html')
    except Exception as e:
        return render_template('error.html', error=e)


@app.route('/victims/<uid>/info', methods=['GET'])
@login_required
def victimobject(uid):
    try:
        http = Indicator.query.filter(Indicator.object == uid).first()
        newdict = libs.helpers.row_to_dict(http)
        settings = Setting.query.filter_by(_id=1).first()
        taglist = http.tags.split(",")

        temprel = {}
        if http.relationships:
            rellist = http.relationships.split(",")
            for rel in rellist:
                reltype = Indicator.query.filter(Indicator.object == rel)
                temprel[reltype.object] = reltype.type

        reldata = len(temprel)
        jsonvt = ""
        whoisdata = ""
        odnsdata = ""
        circldata = ""
        circlssl = ""
        ptdata = ""
        farsightdata = ""
        shodaninfo = ""
        # Run ipwhois or domainwhois based on the type of indicator
        if str(http.type) == "IPv4" or str(http.type) == "IPv6":
            if settings.vtinfo == "on":
                jsonvt = libs.virustotal.vt_ipv4_lookup(str(http.object))
            if settings.whoisinfo == "on":
                whoisdata = libs.whoisinfo.ipwhois(str(http.object))
            if settings.odnsinfo == "on":
                odnsdata = libs.investigate.ip_query(str(http.object))
            if settings.circlinfo == "on":
                circldata = libs.circl.circlquery(str(http.object))
            if settings.circlssl == "on":
                circlssl = libs.circl.circlssl(str(http.object))
            if settings.ptinfo == "on":
                ptdata = libs.passivetotal.pt(str(http.object))
            if settings.farsightinfo == "on":
                farsightdata = libs.farsight.farsightip(str(http.object))
        elif str(http.type) == "Domain":
            if settings.whoisinfo == "on":
                whoisdata = libs.whoisinfo.domainwhois(str(http.object))
            if settings.vtinfo == "on":
                jsonvt = libs.virustotal.vt_domain_lookup(str(http.object))
            if settings.odnsinfo == "on":
                odnsdata = libs.investigate.domain_categories(
                    str(http.object))
            if settings.circlinfo == "on":
                circldata = libs.circl.circlquery(str(http.object))
            if settings.ptinfo == "on":
                ptdata = libs.passivetotal.pt(str(http.object))
        if settings.whoisinfo == "on":
            if str(http.type) == "Domain":
                address = str(whoisdata['city']) + ", " + str(
                    whoisdata['country'])
            else:
                address = str(whoisdata['nets'][0]['city']) + ", " + str(
                    whoisdata['nets'][0]['country'])
        else:
            address = "Information about " + str(http.object)
        return render_template(
            'victimobject.html', records=newdict, jsonvt=jsonvt, whoisdata=whoisdata,
            odnsdata=odnsdata, circldata=circldata, circlssl=circlssl, settingsvars=settings, address=address,
            temprel=temprel, reldata=reldata, taglist=taglist, ptdata=ptdata, farsightdata=farsightdata)
    except Exception as e:
        return render_template('error.html', error=e)


@app.route('/files/<uid>/info', methods=['GET'])
@login_required
def filesobject(uid):
    try:
        http = Indicator.query.filter(Indicator.object == uid).first()
        newdict = libs.helpers.row_to_dict(http)
        settings = Setting.query.filter_by(_id=1).first()
        taglist = http.tags.split(",")

        temprel = {}
        if http.relationships:
            rellist = http.relationships.split(",")
            for rel in rellist:
                reltype = Indicator.query.filter(Indicator.object == rel)
                temprel[reltype.object] = reltype.type

        reldata = len(temprel)
        if settings.vtfile == "on":
            jsonvt = libs.virustotal.vt_hash_lookup(str(http.object))
        else:
            jsonvt=""
        return render_template('fileobject.html', records=newdict, settingsvars=settings, address=http.object,
                               temprel=temprel, reldata=reldata, jsonvt=jsonvt, taglist=taglist)
    except Exception as e:
        return render_template('error.html', error=e)


@app.route('/import', methods=['GET', 'POST'])
@login_required
def import_indicators():
    cuckoo_tasks = libs.cuckoo.get_tasks()
    return render_template('import.html', cuckoo_tasks=cuckoo_tasks)


@app.route('/download/<uid>', methods=['GET'])
@login_required
def download(uid):
    if uid == 'unknown':
        uid = ""
    file = io.BytesIO()

    con = libs.helpers.db_connection()
    indlist = []
    with con:
        cur = con.cursor()
        cur.execute(
            "SELECT * FROM indicators WHERE campaign = '" + str(uid) + "'")
        http = cur.fetchall()
        cur.execute("SELECT * from indicators")
        fieldnames = [description[0] for description in cur.description]

    for i in http:
        indicators = []
        for item in i:
            if item is None or item == "":
                indicators.append("-")
            else:
                indicators.append(str(item))
        indlist.append(indicators)

    w = csv.writer(file)
    try:
        w.writerow(fieldnames)
        w.writerows(indlist)
        response = make_response(file.getvalue())
        response.headers[
            "Content-Disposition"] = "attachment; filename=" + uid + "-campaign.csv"
        response.headers["Content-type"] = "text/csv"
        return response
    except Exception as e:
        print str(e)
        pass


@app.route('/api/v1/indicators', methods=['GET'])
def get_indicators():
    con = libs.helpers.db_connection()
    indicatorlist = []
    with con:
        cur = con.cursor()
        cur.execute("SELECT * FROM indicators")
        indicators = cur.fetchall()
        names = [description[0] for description in cur.description]
        for ind in indicators:
            newdict = {}
            for i in names:
                newdict[i] = str(ind[i])
            indicatorlist.append(newdict)
    return jsonify({'indicators': indicatorlist})


@app.route('/api/v1/ip_indicator/<ip>', methods=['GET'])
def get_ip_indicator(ip):
    con = libs.helpers.db_connection()
    indicatorlist = []
    with con:
        cur = con.cursor()
        cur.execute("SELECT * FROM indicators where object='" + ip + "'")
        indicators = cur.fetchall()
        names = [description[0] for description in cur.description]
        for ind in indicators:
            newdict = {}
            for i in names:
                newdict[i] = str(ind[i])
            indicatorlist.append(newdict)
    return jsonify({'indicator': indicatorlist})


@app.route('/api/v1/network', methods=['GET'])
def get_network():
    con = libs.helpers.db_connection()
    indicatorlist = []
    with con:
        cur = con.cursor()
        cur.execute("SELECT * FROM indicators where type='IPv4' or type='IPv6' or type='Domain' or type='Network'")
        indicators = cur.fetchall()
        names = [description[0] for description in cur.description]
        for ind in indicators:
            newdict = {}
            for i in names:
                newdict[i] = str(ind[i])
            indicatorlist.append(newdict)
    return jsonify({'network_indicators': indicatorlist})


@app.route('/api/v1/threatactors', methods=['GET'])
def get_threatactors():
    con = libs.helpers.db_connection()
    indicatorlist = []
    with con:
        cur = con.cursor()
        cur.execute("SELECT * FROM indicators where type='Threat Actor'")
        indicators = cur.fetchall()
        names = [description[0] for description in cur.description]
        for ind in indicators:
            newdict = {}
            for i in names:
                newdict[i] = str(ind[i])
            indicatorlist.append(newdict)
    return jsonify({'threatactors': indicatorlist})


@app.route('/api/v1/files', methods=['GET'])
def get_files():
    con = libs.helpers.db_connection()
    indicatorlist = []
    with con:
        cur = con.cursor()
        cur.execute("SELECT * FROM indicators where type='Hash'")
        indicators = cur.fetchall()
        names = [description[0] for description in cur.description]
        for ind in indicators:
            newdict = {}
            for i in names:
                newdict[i] = str(ind[i])
            indicatorlist.append(newdict)
    return jsonify({'files': indicatorlist})


@app.route('/api/v1/campaigns/<campaign>', methods=['GET'])
def get_campaigns(campaign):
    con = libs.helpers.db_connection()
    indicatorlist = []
    campaign = urllib.unquote(campaign).decode('utf8')
    with con:
        cur = con.cursor()
        cur.execute("SELECT * FROM indicators where campaign='" + campaign + "'")
        indicators = cur.fetchall()
        names = [description[0] for description in cur.description]
        for ind in indicators:
            newdict = {}
            for i in names:
                newdict[i] = str(ind[i])
            indicatorlist.append(newdict)
    return jsonify({'campaigns': indicatorlist})


@app.route('/api/v1/relationships/<ip>', methods=['GET'])
def get_relationships(ip):
    con = libs.helpers.db_connection()
    indicatorlist = []
    with con:
        cur = con.cursor()
        cur.execute("SELECT relationships from indicators where object='" + ip + "'")
        rels = cur.fetchall()
        rels = rels[0][0]
        rellist = rels.split(",")
        temprel = {}
        for rel in rellist:
            try:
                with con:
                    cur = con.cursor()
                    cur.execute("SELECT * from indicators where object='" + str(rel) + "'")
                    reltype = cur.fetchall()
                    reltype = reltype[0]
                    temprel[reltype['object']] = reltype['type'] 
            except:
                pass
    return jsonify({'relationships': temprel})


@app.teardown_appcontext
def shutdown_session(exception=None):
    db_session.remove()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-p', '--port', help="Specify port to listen on")
    parser.add_argument('-d', '--debug', help="Run in debug mode", action="store_true")
    parser.add_argument('-db', '--database', help="Path to sqlite database - Not Implemented")
    args = parser.parse_args()

    libs.helpers.setup_db()

    if not args.port:
        port = 8888
    else:
        port = args.port

    if not args.debug:
        debug = False
    else:
        debug = True

    init_db()
    app.run(host='0.0.0.0', port=port, debug=debug)