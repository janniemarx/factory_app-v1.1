from v2.app import db

class Profile(db.Model):
    __tablename__ = 'profile'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    density = db.Column(db.Integer, nullable=True)
    cornices_per_box = db.Column(db.Integer, nullable=True)
    cornices_per_block = db.Column(db.Integer, nullable=True)

    def __repr__(self):
        return f"<Profile {self.code}>"
