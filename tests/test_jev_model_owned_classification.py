"""Headings and familiar phrases cannot replace or overrule Jev judgments."""
from eregion.domain.jev_fit.core import JevFit,job_units


class Reader:
    def __init__(self,required,preferred):
        self.required,self.preferred=required,preferred
        self.calls=[]

    def evaluate(self,state,questions,purpose):
        self.calls.append((state,questions,purpose))
        return {k:{'type':'noul','noul':self.required if k.startswith('e') else self.preferred}
                for k in questions},[]


def test_benefit_vocabulary_does_not_hide_candidate_experience_from_jev():
    jd='Benefits: Candidates must have experience administering health insurance and paid time off programs.'
    reader=Reader(.99,.02)
    requirements,ledger,errors=JevFit(reader).extract(jd)
    assert not errors and len(ledger)==len(job_units(jd))==len(requirements)
    assert reader.calls[0][0]['job_description']==jd
    assert {q['instructions']['span'] for q in reader.calls[0][1].values()}=={u['text'] for u in job_units(jd)}
    assert all(r['level']=='required' and r['p_preferred']==.02 for r in requirements)


def test_heading_cannot_overrule_preference_probability_or_unknown():
    for jd,p,level in [('Preferred qualifications: Python is mandatory.',.01,'required'),
                       ('Requirements: Python would be a bonus.',.99,'preferred')]:
        requirements,_,_=JevFit(Reader(.99,p)).extract(jd)
        assert all(r['level']==level and r['p_preferred']==p for r in requirements)
    requirements,ledger,_=JevFit(Reader(.5,.5)).extract('Benefits: Some unusual candidate condition.')
    assert requirements and all(r['extraction_uncertain'] for r in requirements)
    assert all(row['classification']=='unknown' for row in ledger)
