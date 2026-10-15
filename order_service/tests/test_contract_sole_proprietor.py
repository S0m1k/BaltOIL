from app.services.contract_service import _buyer_sign_name, _is_sole_proprietor


def test_ip_detected_by_12_digit_inn():
    assert _is_sole_proprietor({"name": "Поддубный Иван Константинович", "inn": "781234567890"})


def test_ip_detected_by_name_prefix():
    assert _is_sole_proprietor({"name": "ИП Поддубный Иван Константинович", "inn": None})
    assert _is_sole_proprietor({"name": "Индивидуальный предприниматель Поддубный И.К."})


def test_company_is_not_ip():
    assert not _is_sole_proprietor({"name": "ООО «Ромашка»", "inn": "7812345678"})


def test_ip_sign_name_falls_back_to_name():
    buyer = {"name": "ИП Поддубный Иван Константинович", "inn": "781234567890", "director_name": None}
    assert _buyer_sign_name(buyer) == "Поддубный И.К."
