import logging
from datetime import datetime, timezone

from requests import HTTPError

from .bill.models import Bill
from .council_api import (
    get_bill_sponsors,
    get_current_council_members,
    get_person,
    lookup_bill,
)
from .models import db
from .person.models import CouncilMember, OfficeContact, Person
from .sponsorship.models import CitySponsorship
from .static_data.council_data import COUNCIL_DATA_BY_LEGISLATOR_ID
from .utils import cron_function, now


@cron_function
def add_council_members():
    """Adds basic information about each current council member based on their
    OfficeRecord object in the API. This is missing key fields that need
    to be filled in with other sources."""
    members = get_current_council_members()

    for member in members:
        city_council_person_id = member["OfficeRecordPersonId"]

        existing_council_member = CouncilMember.query.filter_by(
            city_council_person_id=city_council_person_id
        ).one_or_none()
        if existing_council_member:
            council_member = existing_council_member
            person = existing_council_member.person
        else:
            person = Person(type=Person.PersonType.COUNCIL_MEMBER)
            person.council_member = CouncilMember()
            council_member = person.council_member
            db.session.add(person)

        person.name = member["OfficeRecordFullName"]
        # TODO: Figure out what exactly Title should be
        person.title = "City Council Member"
        council_member.city_council_person_id = city_council_person_id
        council_member.term_start = datetime.fromisoformat(
            member["OfficeRecordStartDate"]
        ).replace(tzinfo=timezone.utc)
        council_member.term_end = datetime.fromisoformat(
            member["OfficeRecordEndDate"]
        ).replace(tzinfo=timezone.utc)

    db.session.commit()


@cron_function
def fill_council_person_data_from_api():
    """For all council members in the DB, updates their contact info and other details
    based on the Person API and our own static data.
    """
    council_members = CouncilMember.query.all()

    for council_member in council_members:
        try:
            data = get_person(council_member.city_council_person_id)
            council_member.person.email = data["PersonEmail"]
            council_member.website = data["PersonWWW"]

            council_member.person.office_contacts.clear()
            if legislative_phone := data.get("PersonPhone"):
                council_member.person.office_contacts.append(
                    OfficeContact(
                        phone=legislative_phone.strip(),
                        type=OfficeContact.OfficeContactType.CENTRAL_OFFICE,
                    )
                )
            if district_phone := data.get("PersonPhone2"):
                council_member.person.office_contacts.append(
                    OfficeContact(
                        phone=district_phone.strip(),
                        type=OfficeContact.OfficeContactType.DISTRICT_OFFICE,
                    )
                )

            # Borough exists here but we prefer the cleaned static data
            # council_member.borough = data["PersonCity1"]
        except HTTPError:
            logging.exception(
                f"Could not get Person {council_member.city_council_person_id} from API"
            )
            continue

    db.session.commit()


@cron_function
def fill_council_person_static_data():
    council_members = CouncilMember.query.all()

    for council_member in council_members:
        member_data = COUNCIL_DATA_BY_LEGISLATOR_ID.get(
            council_member.city_council_person_id
        )
        if not member_data:
            logging.warning(
                f"Found a legislator without static data: {council_member.city_council_person_id} {council_member.person.name}"
            )
        else:
            council_member.person.twitter = member_data["twitter"]
            council_member.person.party = member_data["party"]

            # Name and borough both exist in the API but the static data has a
            # cleaned-up version.
            council_member.person.name = member_data["name"]
            council_member.borough = member_data["borough"]

    legislator_ids_from_db = set(
        [l.city_council_person_id for l in council_members]
    )
    if diff := set(COUNCIL_DATA_BY_LEGISLATOR_ID.keys()).difference(
        legislator_ids_from_db
    ):
        unmatched_static_data = [
            COUNCIL_DATA_BY_LEGISLATOR_ID[id] for id in diff
        ]
        logging.warning(
            f"Static data has some legislators not in the DB: {unmatched_static_data}"
        )

    db.session.commit()


# Bills ----------------------------------------------------------------------


def _update_bill(bill):
    bill_data = lookup_bill(bill.city_bill.city_bill_id)
    logging.info(
        f"Updating bill {bill.city_bill.city_bill_id} and got {bill_data}"
    )

    bill.name = bill_data["name"]
    bill.description = bill_data["description"]
    for key in bill_data["city_bill"].keys():
        setattr(bill.city_bill, key, bill_data["city_bill"][key])


def sync_bill_updates():
    bills = Bill.query.filter_by(type=Bill.BillType.CITY).all()

    for bill in bills:
        _update_bill(bill)
        db.session.commit()


def update_bill_sponsorships(city_bill, set_added_at=False):
    """
    Updates sponsorships for a given bill:
    1) Deletes any previous sponsorships
    2) Adds all new sponsorships
    3) If new sponsors aren't in the existing legislators (e.g. they're not longer in office),
       ignore them.
    """

    # TODO: Simplify this. We don't need to track added_at, therefore we can just wipe the sponsorships each time and start fresh
    logging.info(f"Updating sponsorships for {city_bill.file}")
    previous_bill_sponsorships = CitySponsorship.query.filter_by(
        bill_id=city_bill.bill_id
    ).all()
    previous_bill_sponsorships_by_id = {
        s.council_member.city_council_person_id: s
        for s in previous_bill_sponsorships
    }

    updated_bill_sponsorships = get_bill_sponsors(
        city_bill.city_bill_id, city_bill.active_version
    )

    council_members_for_updated_sponsorships = CouncilMember.query.filter(
        CouncilMember.city_council_person_id.in_(
            [s["MatterSponsorNameId"] for s in updated_bill_sponsorships]
        )
    ).all()
    council_members_for_updated_sponsorships_by_id = {
        c.city_council_person_id: c
        for c in council_members_for_updated_sponsorships
    }

    for sponsorship_data in updated_bill_sponsorships:
        council_member_person_id = sponsorship_data["MatterSponsorNameId"]

        if (
            council_member_person_id
            not in council_members_for_updated_sponsorships_by_id
        ):
            # Can't insert the sponsorship without its foreign key object
            # TODO: Instead, insert a stub for them or something
            logging.warning(
                f"Did not find legislator {council_member_person_id} in db, ignoring..."
            )
            continue

        sponsorship = previous_bill_sponsorships_by_id.get(
            council_member_person_id
        )
        if sponsorship:
            logging.info(
                f"Sponsorship already exists for {sponsorship.person.name}"
            )
            # Remove sponsors from this set until we're left with only those
            # sponsorships that were rescinded recently.
            del previous_bill_sponsorships_by_id[council_member_person_id]
        else:
            logging.info(
                f"Adding new sponsorship for {council_members_for_updated_sponsorships_by_id[council_member_person_id].person.name}"
            )
            sponsorship = CitySponsorship(
                bill_id=city_bill.bill_id,
                council_member_id=council_members_for_updated_sponsorships_by_id[
                    council_member_person_id
                ].person_id,
                sponsor_sequence=sponsorship_data["MatterSponsorSequence"],
            )
            if set_added_at:
                sponsorship.added_at = now()

            db.session.add(sponsorship)

    for lost_sponsor in previous_bill_sponsorships_by_id.values():
        db.session.delete(lost_sponsor)


@cron_function
def update_all_sponsorships():
    bills = Bill.query.filter_by(type=Bill.BillType.CITY).all()
    for bill in bills:
        logging.info(f"Updating sponsorships for bill {bill.id} {bill.name}")
        try:
            update_bill_sponsorships(bill.city_bill, set_added_at=True)
            db.session.commit()
        except Exception:
            db.session.rollback()
            logging.exception(
                f"Exception while updating sponsorships for {bill.city_bill.city_bill_id}"
            )
