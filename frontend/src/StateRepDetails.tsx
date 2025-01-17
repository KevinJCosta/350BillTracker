import { Person, StateRepresentative, OfficeContact } from './types';
import React, { useState } from 'react';
import styles from './style/PersonDetailsPanel.module.scss';
import useMountEffect from '@restart/hooks/esm/useMountEffect';
import useApiFetch from './useApiFetch';

interface Props {
  person: Person;
  representativeDetails: StateRepresentative;
}

function ContactPanel({ contact }: { contact: OfficeContact }) {
  return (
    <div className="mb-2">
      {contact.city && (
        <div style={{ fontWeight: 'bold' }}>{contact.city} office</div>
      )}
      {contact.phone && <div>Phone: {contact.phone}</div>}
      {contact.fax && <div>Fax: {contact.fax}</div>}
    </div>
  );
}

export default function StateRepDetails(props: Props) {
  const person = props.person;

  const website = props.representativeDetails.website;

  const [contacts, setContacts] = useState<OfficeContact[] | null>(null);

  const apiFetch = useApiFetch();

  useMountEffect(() => {
    apiFetch(`/api/persons/${person.id}/contacts`).then((response) => {
      setContacts(response);
    });
  });

  // TODO: Display their sponsorships here, too (can do in later PR from State impl)
  return (
    <>
      <div className={styles.label}>Name</div>
      <div className={styles.content}>{person.name}</div>
      <div className={styles.label}>Title</div>
      <div className={styles.content}>{person.title}</div>
      <div className={styles.label}>Email</div>
      <div className={styles.content}>{person.email}</div>
      <div className={styles.label}>Contact info</div>
      <div className={styles.content}>
        {contacts &&
          contacts.map((contact, index) => (
            <ContactPanel contact={contact} key={index} />
          ))}
      </div>
      <div className={styles.label}>Party</div>
      <div className={styles.content}>{person.party}</div>
      <div className={styles.label}>District website</div>
      <div className={styles.content}>
        {website && (
          <a href={website} target="_blank" rel="noreferrer">
            District {props.representativeDetails.district}
          </a>
        )}
      </div>
      <div className={styles.label}>Twitter</div>
      <div className={styles.content}>
        {person.twitter && (
          <a href={`https://twitter.com/${person.twitter}`} target="twitter">
            @{person.twitter}
          </a>
        )}
      </div>
    </>
  );
}
