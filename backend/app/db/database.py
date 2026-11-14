from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

DATABASE_URL = "sqlite:///./solar_energy.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Site(Base):
    __tablename__ = "sites"

    site_id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    sla_availability_pct = Column(Float, default=96.0)
    status = Column(String, default="OK")  # OK, WARNING, CRITICAL

    # Relatie 1-la-N: un site are mai multe invertoare
    inverters = relationship("Inverter", back_populates="site", cascade="all, delete-orphan")


class Inverter(Base):
    __tablename__ = "inverters"

    inverter_id = Column(String, primary_key=True, index=True)
    site_id = Column(String, ForeignKey("sites.site_id"), index=True, nullable=False)
    name = Column(String, nullable=False)          # ex: "Invertor Hala Est"
    brand = Column(String, nullable=False)         # Huawei, Fronius, SMA
    rated_power_kw = Column(Float, nullable=False) # Capacitatea instalata (kW)
    current_power_kw = Column(Float, default=0.0)
    expected_power_kw = Column(Float, default=0.0)
    status = Column(String, default="OK")          # OK, WARNING, CRITICAL
    # Parametri optionali (pot fi None daca producatorul nu ii expune)
    battery_soc_pct = Column(Float, nullable=True)
    gsm_signal_dbm = Column(Integer, nullable=True)

    site = relationship("Site", back_populates="inverters")


class LoadCurve15Min(Base):
    __tablename__ = "load_curves"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    site_id = Column(String, ForeignKey("sites.site_id"), index=True, nullable=False)
    start_time = Column(DateTime, index=True, nullable=False)
    end_time = Column(DateTime, nullable=False)
    interval_no = Column(Integer, nullable=False)
    energy_mwh = Column(Float, nullable=False)
    avg_power_mw = Column(Float, nullable=False)
    observatii = Column(String, nullable=True)


class Alert(Base):
    __tablename__ = "alerts"

    alert_id = Column(String, primary_key=True, index=True)
    site_id = Column(String, ForeignKey("sites.site_id"), index=True, nullable=False)
    inverter_id = Column(String, ForeignKey("inverters.inverter_id"), nullable=True)
    severity = Column(String, nullable=False)
    message = Column(String, nullable=False)
    estimated_loss_kwh = Column(Float, default=0.0)
    resolved = Column(Integer, default=0)


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()